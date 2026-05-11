import asyncio
import logging
import threading
import subprocess
import sys
import os
from datetime import datetime
from sqlalchemy.future import select
from sqlalchemy import func
from app.core.database import AsyncSessionLocal
from app.models.sql_models import Task, Post, Comment, Sentiment, AnalysisResult, SystemConfig
from app.crawler.crawler import SocialMediaCrawler
from app.sentiment.analyzer import SentimentAnalyzer
from app.services.dashboard_service import DashboardService
from app.services.text_analysis import TextAnalysisService

logger = logging.getLogger(__name__)
USER_CONTROL_MESSAGES = {"任务已暂停", "Stopped by user"}

# Global dictionary to track running crawler processes
# {task_id: subprocess.Popen}
_running_processes = {}

async def stop_task_process(task_id: int):
    """Stop a running task process"""
    process = _running_processes.get(task_id)
    if process:
        try:
            process.terminate()
            # Wait a bit for it to terminate
            try:
                # subprocess.Popen.wait is synchronous, use to_thread
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
            logger.info(f"Terminated process for task {task_id}")
        except Exception as e:
            logger.error(f"Error terminating process for task {task_id}: {e}")
        finally:
            _running_processes.pop(task_id, None)


def _is_user_interrupted(task: Task) -> bool:
    return task.status == "paused" or task.progress_message in USER_CONTROL_MESSAGES

async def run_task_logic(task_id: int):
    """
    Core logic for running a task: Crawl -> Sentiment Analysis -> Update Status
    """
    # 避免在 BackgroundTasks 中直接运行可能冲突的 event loop 操作
    # 但在这里我们是在一个新的 task 中运行，应该没问题
    # 关键是确保整个进程使用 ProactorEventLoopPolicy
    try:
        async with AsyncSessionLocal() as session:
            # 1. Get Task and System Settings
            result = await session.execute(select(Task).filter_by(id=task_id))
            task = result.scalars().first()
            
            if not task:
                logger.error(f"Task {task_id} not found")
                return

            # Get task timeout from system settings
            config_result = await session.execute(select(SystemConfig).filter_by(key="system"))
            system_config = config_result.scalars().first()
            task_timeout = 3600 # Default 1 hour
            if system_config and "task_timeout" in system_config.value:
                task_timeout = int(system_config.value["task_timeout"])
            
            logger.info(f"Task {task_id} will run with timeout {task_timeout}s")

            try:
                # 任务状态是前端展示执行进度的主要依据，
                # 因此在每个阶段切换时均需及时回写数据库。
                # Update status to running
                task.status = 'running'
                task.progress = 0.0
                task.progress_message = "开始执行任务..."
                if not task.started_at:
                    task.started_at = datetime.now()
                await session.commit()
                logger.info(f"Task {task_id} started running")
                
                # 采集阶段放在独立子进程中执行。
                # 该设计用于规避 Windows 环境下 Playwright 与主事件循环的兼容问题，
                # 同时降低采集异常对主服务稳定性的影响。
                # 2. Run Crawler
                # 使用独立的子进程运行爬虫，彻底解决 Windows Event Loop 兼容性问题
                # (Use a separate subprocess for the crawler to solve Windows Event Loop compatibility issues)
                
                task.progress = 5.0
                task.progress_message = f"正在启动 {task.platform} 爬虫进程..."
                await session.commit()
                
                # Launch worker process
                logger.info(f"Launching crawler worker for task {task_id}")
                
                # Use subprocess.Popen instead of create_subprocess_exec to avoid 
                # NotImplementedError on Windows when loop is not Proactor
                process = subprocess.Popen(
                    [sys.executable, "-m", "app.crawler.worker", str(task_id)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=os.getcwd(),
                    text=True
                )
                
                _running_processes[task_id] = process
                
                try:
                    # Run communicate in a thread to avoid blocking the event loop
                    # Apply task timeout
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            asyncio.to_thread(process.communicate),
                            timeout=float(task_timeout)
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"Task {task_id} timed out after {task_timeout} seconds")
                        process.kill()
                        raise Exception(f"任务执行超时（限制为 {task_timeout} 秒）")
                    
                    if process.returncode != 0:
                        logger.error(f"Crawler worker failed with code {process.returncode}")
                        err_msg = stderr if stderr else "Unknown error"
                        logger.error(f"Worker stderr: {err_msg}")
                        raise Exception(f"Crawler worker process failed: {err_msg[-200:]}")
                    
                    logger.info(f"Crawler worker finished successfully")
                finally:
                    _running_processes.pop(task_id, None)
                
            except Exception as e:
                # Catch crawler specific errors
                logger.exception(f"Crawler failed for task {task_id}")
                # Re-acquire task/session to update status
                async with AsyncSessionLocal() as error_session:
                     result = await error_session.execute(select(Task).filter_by(id=task_id))
                     task = result.scalars().first()
                     if task:
                        if _is_user_interrupted(task):
                            return
                        task.status = 'failed'
                        task.progress_message = f"爬虫启动失败: {str(e)}"
                        await error_session.commit()
                return

            # Re-acquire task for sentiment analysis phase (crawler session closed)
            # Actually we are in the same outer session, so task is still attached
            # But we should refresh it to get latest updates from worker
            await session.refresh(task)
            
            if task.status == 'failed' or _is_user_interrupted(task):
                return
            
            # 3. Sentiment Analysis
            try:
                task.progress = 60.0
                task.progress_message = "准备进行情感分析..."
                await session.commit()

                stmt = select(Comment).join(Post).filter(Post.task_id == task_id)
                result = await session.execute(stmt)
                comments = result.scalars().all()
                
                if comments:
                    total_comments = len(comments)
                    logger.info(f"Starting sentiment analysis for {total_comments} comments")
                    
                    # 初始化分析器（使用全局单例）
                    analyzer = SentimentAnalyzer()
                    
                    # 情感分析采用分批处理方式，
                    # 以避免评论规模较大时出现内存占用过高的问题。
                    # 批处理大小
                    batch_size = 100
                    
                    for i in range(0, total_comments, batch_size):
                        batch_comments = comments[i:i+batch_size]
                        texts = [c.content or "" for c in batch_comments]
                        
                        try:
                            # 批量预测
                            results = await asyncio.to_thread(analyzer.predict_batch, texts, 32)
                            
                            # 保存结果
                            for idx, res in enumerate(results):
                                comment = batch_comments[idx]
                                
                                # 检查是否已存在
                                stmt_sent = select(Sentiment).filter_by(comment_id=comment.id)
                                res_sent = await session.execute(stmt_sent)
                                if res_sent.scalars().first():
                                    continue
                                
                                new_sentiment = Sentiment(
                                    comment_id=comment.id,
                                    sentiment_label=res['sentiment'],
                                    confidence=res['confidence'],
                                    model_version=analyzer.get_model_info()['model_name']
                                )
                                session.add(new_sentiment)
                            
                            # Update progress
                            processed_count = min(i + batch_size, total_comments)
                            progress_pct = 60.0 + (processed_count / total_comments) * 35.0 # 60% -> 95%
                            task.progress = round(progress_pct, 1)
                            task.progress_message = f"情感分析中: {processed_count}/{total_comments}..."

                            # 每批提交一次，避免长事务和内存占用
                            await session.commit()
                            await session.refresh(task)
                            if _is_user_interrupted(task):
                                return
                            logger.info(f"Analyzed and saved batch {i//batch_size + 1}/{(total_comments + batch_size - 1)//batch_size}")
                            
                        except Exception as e:
                            logger.error(f"Error analyzing batch {i}: {e}")
                            # 即使这一批失败，也尝试继续下一批
                            await session.rollback()
                            continue
                            
                    # 在单条评论情感分类完成后，进一步生成任务级聚合结果，
                    # 供前端图表展示与报告导出直接使用。
                    # 4. Generate Aggregated Analysis Result
                    logger.info(f"Generating aggregated analysis result for task {task_id}")
                    task.progress = 95.0
                    task.progress_message = "正在生成汇总分析报告..."
                    await session.commit()

                    # Get all sentiments for this task
                    stmt_all_sent = select(Sentiment).join(Comment).join(Post).filter(Post.task_id == task_id)
                    res_all_sent = await session.execute(stmt_all_sent)
                    all_sentiments = res_all_sent.scalars().all()

                    dist = {'positive': 0, 'neutral': 0, 'negative': 0}
                    for s in all_sentiments:
                        dist[s.sentiment_label] += 1
                    
                    # Perform Word Cloud and LDA Analysis
                    logger.info(f"Performing multi-source text analysis for task {task_id}")
                    text_service = TextAnalysisService()
                    
                    # Get all text content
                    stmt_posts = select(Post).filter_by(task_id=task_id)
                    res_posts = await session.execute(stmt_posts)
                    posts_content = [p.content for p in res_posts.scalars().all() if p.content]
                    
                    stmt_comments = select(Comment).join(Post).filter(Post.task_id == task_id)
                    res_comments = await session.execute(stmt_comments)
                    comments_content = [c.content for c in res_comments.scalars().all() if c.content]
                    
                    all_texts = posts_content + comments_content
                    
                    # Calculate results for each source type
                    word_cloud_multi = {
                        "all": text_service.generate_word_cloud_data(all_texts),
                        "posts": text_service.generate_word_cloud_data(posts_content),
                        "comments": text_service.generate_word_cloud_data(comments_content)
                    }
                    
                    lda_topics_multi = {
                        "all": text_service.perform_lda_analysis(all_texts),
                        "posts": text_service.perform_lda_analysis(posts_content),
                        "comments": text_service.perform_lda_analysis(comments_content)
                    }

                    # 趋势数据按照“日期 + 情感类别”进行二次聚合，
                    # 最终用于前端趋势图展示舆情变化过程。
                    # Calculate real trend data (sentiment by day)
                    logger.info(f"Calculating sentiment trend for task {task_id}")
                    # Group comments by date and sentiment
                    # stmt_trend = select(func.date(Comment.comment_time), Sentiment.sentiment_label, func.count()) \
                    #     .join(Sentiment).join(Post).filter(Post.task_id == task_id) \
                    #     .group_by(func.date(Comment.comment_time), Sentiment.sentiment_label)
                    # Note: SQLite/MySQL date functions differ. For portability, we can do it in Python if not too many comments
                    trend_map = {} # {date: {pos: 0, neu: 0, neg: 0}}
                    
                    stmt_trend = select(Comment.comment_time, Sentiment.sentiment_label) \
                        .join(Sentiment).join(Post).filter(Post.task_id == task_id)
                    res_trend = await session.execute(stmt_trend)
                    for row in res_trend:
                        dt, label = row
                        if not dt: continue
                        date_str = dt.strftime("%Y-%m-%d")
                        if date_str not in trend_map:
                            trend_map[date_str] = {"positive": 0, "neutral": 0, "negative": 0}
                        trend_map[date_str][label] += 1
                    
                    trend_data = []
                    for date_str in sorted(trend_map.keys()):
                        item = trend_map[date_str]
                        trend_data.append({
                            "date": date_str,
                            "positive": item["positive"],
                            "neutral": item["neutral"],
                            "negative": item["negative"]
                        })

                    # Check if analysis result already exists
                    stmt_ar = select(AnalysisResult).filter_by(task_id=task_id)
                    res_ar = await session.execute(stmt_ar)
                    analysis_res = res_ar.scalars().first()

                    # 保存简要摘要，便于任务详情页与问答模块快速获取总体结论。
                    summary_text = f"本次分析共处理 {len(posts_content)} 条帖子和 {len(comments_content)} 条评论，整体情感倾向为 {max(dist, key=dist.get) if all_sentiments else '未知'}。"

                    if not analysis_res:
                        analysis_res = AnalysisResult(
                            task_id=task_id,
                            sentiment_distribution=dist,
                            word_cloud=word_cloud_multi,
                            lda_topics=lda_topics_multi,
                            trend_data=trend_data,
                            summary=summary_text
                        )
                        session.add(analysis_res)
                    else:
                        analysis_res.sentiment_distribution = dist
                        analysis_res.word_cloud = word_cloud_multi
                        analysis_res.lda_topics = lda_topics_multi
                        analysis_res.trend_data = trend_data
                        analysis_res.summary = summary_text
                    
                    await session.commit()
                    logger.info("Multi-source analysis result saved successfully")
                    await DashboardService.refresh_total_collected_cache(session)
                    
            except Exception as e:
                logger.error(f"Sentiment analysis or aggregation failed: {e}")
                task.status = 'failed'
                task.progress_message = f"分析失败: {str(e)}"
                await session.commit()
                return
            
            # 5. Complete
            await session.refresh(task)
            if _is_user_interrupted(task):
                return
            task.status = 'completed'
            task.progress = 100.0
            task.progress_message = "任务已完成"
            task.completed_at = datetime.now()
            await session.commit()
            logger.info(f"Task {task_id} completed successfully")
            
    except Exception as e:
        logger.error(f"Task {task_id} failed with unhandled exception: {e}")
        # Try to update status if possible
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(select(Task).filter_by(id=task_id))
                task = result.scalars().first()
                if task:
                    if _is_user_interrupted(task):
                        return
                    task.status = 'failed'
                    task.progress_message = f"系统错误: {str(e)}"
                    await session.commit()
        except:
            pass
