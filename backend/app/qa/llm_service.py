# 大模型问答模块
import os
# Set Hugging Face Mirror
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

import json
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
from datetime import datetime
import numpy as np
import torch
from sentence_transformers import SentenceTransformer, util
from openai import AsyncOpenAI
import httpx

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LLMQuestionAnswering:
    """大模型问答系统 (基于向量检索 RAG)"""
    
    def __init__(self, api_key: str, api_base: str = None, model: str = "qwen-plus", embedding_model: str = "moka-ai/m3e-base"):
        # Use user provided key if not provided or mock
        if not api_key or api_key == "mock-key":
             api_key = ""#需要自己的密钥

        self.api_key = api_key
        self.api_base = api_base or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.model = model
        
        # 初始化OpenAI客户端 (Async)
        try:
            # Explicitly use httpx.AsyncClient to avoid proxies issue with newer httpx versions
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
                http_client=httpx.AsyncClient()
            )
            logger.info(f"AsyncOpenAI client initialized with base_url: {self.api_base}")
        except Exception as e:
            logger.error(f"Failed to initialize AsyncOpenAI client: {e}")
            self.client = None
        
        self.document_vectors = None
        self.documents = []
        self.fixed_documents = []
        self.searchable_documents = []
        
        # 初始化 Embedding 模型
        try:
            logger.info(f"Loading embedding model: {embedding_model}...")
            # 强制使用 cpu 以避免显存问题，对于推理，CPU 足够。
            self.embedding_model = SentenceTransformer(embedding_model, device='cpu')
            logger.info("Embedding model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.embedding_model = None
            
        logger.info(f"LLM QA initialized with model: {self.model}")
    
    def set_context_documents(self, documents: List[Dict]):
        """设置上下文文档"""
        try:
            self.documents = documents
            
            # 将上下文划分为固定上下文与可检索上下文。
            # 固定上下文用于提供任务背景，可检索上下文用于按问题语义动态召回。
            self.fixed_documents = []
            self.searchable_documents = []
            
            for doc in documents:
                if doc.get('type') in ['metadata', 'analysis', 'analysis_result']:
                    self.fixed_documents.append(doc)
                else:
                    self.searchable_documents.append(doc)
            
            if not self.embedding_model:
                logger.warning("Embedding model not initialized, skipping vectorization.")
                self.document_vectors = None
                return

            # 仅对可检索文档执行向量化，避免对固定说明性文本重复计算。
            texts = []
            for doc in self.searchable_documents:
                # 组合标题和内容
                text = f"{doc.get('title', '')} {doc.get('content', '')}"
                texts.append(text)
            
            if texts:
                # 创建 Embedding 向量
                logger.info(f"Encoding {len(texts)} documents...")
                self.document_vectors = self.embedding_model.encode(texts, convert_to_tensor=True)
                logger.info(f"Indexed {len(self.searchable_documents)} searchable documents and kept {len(self.fixed_documents)} fixed documents")
            else:
                logger.warning("No valid searchable documents to index")
                self.document_vectors = None
                
        except Exception as e:
            logger.error(f"Failed to set context documents: {str(e)}")
            self.documents = []
            self.fixed_documents = []
            self.searchable_documents = []
            self.document_vectors = None
    
    def retrieve_relevant_documents(self, query: str, top_k: int = 15) -> List[Dict]:
        """检索相关文档 (基于向量相似度)"""
        try:
            # 固定上下文始终参与回答构造，以保证回答具备稳定的任务背景。
            results = self.fixed_documents.copy()
            
            if not self.searchable_documents or self.document_vectors is None or not self.embedding_model:
                return results
            
            # 将用户问题编码为向量表示。
            query_embedding = self.embedding_model.encode(query, convert_to_tensor=True)
            
            # 基于余弦相似度计算问题与候选文本之间的语义接近程度。
            # util.cos_sim 返回 (num_queries, num_corpus)
            cos_scores = util.cos_sim(query_embedding, self.document_vectors)[0]
            
            # 获取最相关的文档索引
            actual_top_k = min(top_k, len(self.searchable_documents))
            
            # torch.topk 返回 (values, indices)
            top_results = torch.topk(cos_scores, k=actual_top_k)
            
            retrieved_count = 0
            
            for score, idx in zip(top_results[0], top_results[1]):
                idx = int(idx)
                score = float(score)
                
                # 通过相似度阈值过滤低相关文本，减少无关上下文干扰。
                if score > 0.1: 
                    doc = self.searchable_documents[idx].copy()
                    doc['relevance_score'] = score
                    results.append(doc)
                    retrieved_count += 1
            
            # 当高相关文本数量不足时，补充少量原始文本作为兜底上下文，
            # 用于避免回答因上下文过少而过于空泛。
            if retrieved_count < 3 and len(self.searchable_documents) > 0:
                needed = 5 - retrieved_count
                for i in range(min(needed, len(self.searchable_documents))):
                    doc = self.searchable_documents[i]
                    # 简单的去重检查
                    is_already_added = False
                    for r in results:
                         if r.get('content') == doc.get('content'):
                             is_already_added = True
                             break
                    
                    if not is_already_added:
                        doc_copy = doc.copy()
                        doc_copy['relevance_score'] = 0.0 # 标记为兜底数据
                        doc_copy['is_fallback'] = True
                        results.append(doc_copy)
            
            logger.info(f"Retrieved {len(results)} documents (including fixed)")
            return results
            
        except Exception as e:
            logger.error(f"Document retrieval failed: {str(e)}")
            # 出错时至少返回固定文档
            return self.fixed_documents
    
    def generate_prompt(self, question: str, context_docs: List[Dict]) -> str:
        """生成提示词"""
        
        # 系统提示词用于约束回答风格与证据边界，
        # 使模型优先依据当前任务数据进行回答。
        if context_docs:
            system_prompt = """你是一个专业的社交媒体数据分析助手。请基于提供的上下文数据，准确、客观地回答用户的问题。
            请使用中文回答，保持回答的准确性和专业性。
            注意：提供的“相关数据”是从完整数据集中根据你的问题匹配出的最相关片段。如果这些片段足以回答问题，请直接回答。
            如果数据明显不足以回答某个具体问题（例如询问某个未提及的具体数值），请明确说明。"""
        else:
            system_prompt = """你是一个专业的AI助手。请基于用户提供的信息和你的知识库，准确、客观地回答用户的问题。
            请使用中文回答，保持回答的准确性和专业性。"""
        
        # 将召回到的文本片段组织为结构化上下文，供大模型统一阅读。
        context_text = ""
        if context_docs:
            context_text = "\n\n相关数据片段：\n"
            for i, doc in enumerate(context_docs, 1):
                title = doc.get('title', '')
                content = doc.get('content', '')
                score = doc.get('relevance_score', 0)
                type_label = doc.get('type', 'general')
                
                context_text += f"\n[{i}] [{type_label}] {title}\n{content}\n(相关度: {score:.3f})\n"
        
        # 构建完整的提示词
        prompt = f"""{system_prompt}
        
        用户问题：{question}
        
        {context_text}
        
        请基于以上信息回答用户的问题。回答应该：
        1. 直接回应用户的问题
        2. 保持客观和专业
        """
        
        return prompt
    
    async def answer_question(self, question: str, use_context: bool = True, top_k: int = 15) -> str:
        """提问并获取回答 (为了兼容 main.py 的调用)"""
        result = await self.ask_question(question, use_context, top_k)
        return result.get('answer', "抱歉，我无法回答这个问题。")

    async def ask_question(self, question: str, use_context: bool = True, top_k: int = 15) -> Dict:
        """提问并获取回答"""
        if not self.client:
             return {
                'question': question,
                'answer': "错误：OpenAI 客户端未初始化。请检查 API 密钥配置。",
                'error': "Client not initialized",
                'timestamp': datetime.now().isoformat()
            }

        try:
            # 检索相关文档
            context_docs = []
            if use_context:
                context_docs = self.retrieve_relevant_documents(question, top_k=top_k)
            
            # 生成提示词
            prompt = self.generate_prompt(question, context_docs)
            
            # 调用大模型API (v1.x)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的社交媒体数据分析助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000
            )
            
            answer = response.choices[0].message.content
            
            # 构建回答结果
            result = {
                'question': question,
                'answer': answer,
                'context_documents': context_docs,
                'model_used': self.model,
                'timestamp': datetime.now().isoformat(),
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
            
            logger.info(f"Question answered successfully using {len(context_docs)} context documents")
            return result
            
        except Exception as e:
            logger.error(f"Question answering failed: {str(e)}")
            return {
                'question': question,
                'answer': f"抱歉，回答问题时出现了错误：{str(e)}",
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    async def stream_answer_question(self, question: str, use_context: bool = True, top_k: int = 15) -> AsyncGenerator[str, None]:
        """流式提问 (为了兼容 main.py 的调用)"""
        async for chunk in self.ask_question_stream(question, use_context, top_k):
            yield chunk

    async def ask_question_stream(self, question: str, use_context: bool = True, top_k: int = 15) -> AsyncGenerator[str, None]:
        """流式提问"""
        if not self.client:
            yield f"data: {json.dumps({'error': 'Client not initialized'})}\n\n"
            return

        try:
            # 检索相关文档
            context_docs = []
            if use_context:
                context_docs = self.retrieve_relevant_documents(question, top_k=top_k)
            
            # 生成提示词
            prompt = self.generate_prompt(question, context_docs)
            
            # 先发送上下文信息
            yield f"data: {json.dumps({'type': 'context', 'sources': context_docs})}\n\n"
            
            # 调用大模型API (Stream)
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的社交媒体数据分析助手。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1000,
                stream=True
            )
            
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    yield f"data: {json.dumps({'type': 'content', 'content': content})}\n\n"
            
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            
        except Exception as e:
            logger.error(f"Stream QA failed: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    async def generate_analysis_report(self, analysis_data: Dict) -> Dict:
        """生成分析报告"""
        try:
            # 构建分析数据上下文
            context_docs = [{
                'title': '情感分析结果',
                'content': self.format_analysis_data(analysis_data),
                'type': 'analysis_result'
            }]
            
            # 设置上下文
            self.set_context_documents(context_docs)
            
            # 生成报告提示
            report_prompt = """
            基于以上情感分析数据，请生成一份详细的分析报告。报告应该包含：
            
            1. 数据概览：总体情感分布情况
            2. 主要发现：最重要的洞察和趋势
            3. 详细分析：各情感类别的具体分析
            4. 建议措施：基于分析结果的建议
            5. 结论：总结性观点
            
            报告应该结构清晰，数据准确，建议实用。
            """
            
            result = await self.ask_question(report_prompt, use_context=True)
            
            # 添加报告元数据
            result['report_type'] = 'sentiment_analysis'
            result['analysis_data'] = analysis_data
            
            return result
            
        except Exception as e:
            logger.error(f"Report generation failed: {str(e)}")
            return {
                'error': str(e),
                'report_type': 'sentiment_analysis',
                'timestamp': datetime.now().isoformat()
            }
    
    def format_analysis_data(self, analysis_data: Dict) -> str:
        """格式化分析数据"""
        formatted = []
        
        # 情感分布
        if 'sentiment_distribution' in analysis_data:
            formatted.append("情感分布:")
            for sentiment, count in analysis_data['sentiment_distribution'].items():
                formatted.append(f"  {sentiment}: {count}")
        
        # 趋势数据
        if 'trend_data' in analysis_data:
            formatted.append("\n趋势数据:")
            for trend in analysis_data['trend_data'][:5]:  # 只显示前5个时间点
                formatted.append(f"  {trend.get('date', '')}: 正面{trend.get('positive', 0)}, "
                               f"中性{trend.get('neutral', 0)}, 负面{trend.get('negative', 0)}")
        
        # 热词
        if 'top_words' in analysis_data:
            formatted.append("\n热词排行:")
            for word, count in analysis_data['top_words'][:10]:
                formatted.append(f"  {word}: {count}")
        
        # 置信度统计
        if 'confidence_stats' in analysis_data:
            stats = analysis_data['confidence_stats']
            formatted.append(f"\n置信度统计:")
            formatted.append(f"  平均置信度: {stats.get('mean', 0):.3f}")
            formatted.append(f"  样本数量: {stats.get('count', 0)}")
        
        return '\n'.join(formatted)
    
    async def chat_with_history(self, messages: List[Dict]) -> Dict:
        """支持历史记录的对话"""
        if not self.client:
            return {'error': 'Client not initialized'}

        try:
            # 提取最后一个问题
            last_message = messages[-1]
            if last_message.get('role') != 'user':
                return {'error': 'Last message must be from user'}
            
            question = last_message['content']
            
            # 检索相关文档（如果需要）
            if self.documents:
                context_docs = self.retrieve_relevant_documents(question)
                if context_docs:
                    # 在系统消息中添加上下文
                    context_text = "\n\n相关数据：\n"
                    for i, doc in enumerate(context_docs, 1):
                        content = doc.get('content', '')
                        context_text += f"\n[{i}] {content}\n"
                    
                    # 修改系统消息 (需要深拷贝避免修改原始消息)
                    import copy
                    messages = copy.deepcopy(messages)
                    for msg in messages:
                        if msg.get('role') == 'system':
                            msg['content'] += context_text
                            break
            
            # 调用API
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=1000
            )
            
            answer = response.choices[0].message.content
            
            return {
                'answer': answer,
                'model_used': self.model,
                'timestamp': datetime.now().isoformat(),
                'usage': {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens
                }
            }
            
        except Exception as e:
            logger.error(f"Chat with history failed: {str(e)}")
            return {
                'answer': f"抱歉，对话时出现了错误：{str(e)}",
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }


class QAService:
    """问答服务"""
    
    def __init__(self, api_key: str, api_base: str = None, model: str = "qwen-plus"):
        self.qa_system = LLMQuestionAnswering(api_key, api_base, model)
        self.conversation_history = []
        
        # 预定义的问题模板
        self.question_templates = {
            'sentiment_summary': '请总结当前的情感分析结果',
            'trend_analysis': '请分析情感趋势变化',
            'improvement_suggestions': '基于分析结果，请提供改进建议',
            'risk_warning': '请识别潜在的风险和负面情感',
            'competitor_analysis': '请分析竞争对手的表现'
        }
    
    def set_analysis_context(self, analysis_data: Dict):
        """设置分析上下文"""
        # 构建上下文文档
        context_docs = []
        
        # 情感分布数据
        if 'sentiment_distribution' in analysis_data:
            context_docs.append({
                'title': '情感分布统计',
                'content': json.dumps(analysis_data['sentiment_distribution'], ensure_ascii=False),
                'type': 'sentiment_stats'
            })
        
        # 趋势数据
        if 'trend_data' in analysis_data:
            context_docs.append({
                'title': '情感趋势数据',
                'content': json.dumps(analysis_data['trend_data'][:10], ensure_ascii=False),  # 只取前10条
                'type': 'trend_data'
            })
        
        # 热词数据
        if 'top_words' in analysis_data:
            context_docs.append({
                'title': '热点词汇',
                'content': json.dumps(analysis_data['top_words'][:20], ensure_ascii=False),
                'type': 'word_analysis'
            })
        
        # 设置上下文
        self.qa_system.set_context_documents(context_docs)
        
        logger.info(f"Set analysis context with {len(context_docs)} documents")
    
    async def ask_predefined_question(self, question_type: str) -> Dict:
        """询问预定义问题"""
        if question_type not in self.question_templates:
            return {'error': f'Unknown question type: {question_type}'}
        
        question = self.question_templates[question_type]
        return await self.qa_system.ask_question(question)
    
    async def ask_custom_question(self, question: str, **kwargs) -> Dict:
        """询问自定义问题"""
        return await self.qa_system.ask_question(question, **kwargs)
    
    async def generate_comprehensive_report(self, analysis_data: Dict) -> Dict:
        """生成综合分析报告"""
        # 设置上下文
        self.set_analysis_context(analysis_data)
        
        # 生成各个部分的报告
        report_sections = {}
        
        # 执行摘要
        summary_response = await self.ask_predefined_question('sentiment_summary')
        report_sections['executive_summary'] = summary_response.get('answer', '')
        
        # 趋势分析
        trend_response = await self.ask_predefined_question('trend_analysis')
        report_sections['trend_analysis'] = trend_response.get('answer', '')
        
        # 风险识别
        risk_response = await self.ask_predefined_question('risk_warning')
        report_sections['risk_assessment'] = risk_response.get('answer', '')
        
        # 改进建议
        suggestions_response = await self.ask_predefined_question('improvement_suggestions')
        report_sections['recommendations'] = suggestions_response.get('answer', '')
        
        # 构建完整报告
        comprehensive_report = {
            'report_type': 'comprehensive_sentiment_analysis',
            'generated_at': datetime.now().isoformat(),
            'sections': report_sections,
            'analysis_data': analysis_data,
            'metadata': {
                'model_used': self.qa_system.model,
                'total_sections': len(report_sections)
            }
        }
        
        return comprehensive_report
    
    async def chat_with_analysis_context(self, question: str, analysis_data: Dict) -> Dict:
        """在分析上下文中进行对话"""
        # 设置上下文
        self.set_analysis_context(analysis_data)
        
        # 构建对话历史
        messages = [
            {'role': 'system', 'content': '你是一个专业的社交媒体数据分析助手。请基于提供的分析数据回答用户的问题。'},
            {'role': 'user', 'content': question}
        ]
        
        return await self.qa_system.chat_with_history(messages)

# 测试函数
async def test_qa_system():
    """测试问答系统"""
    # 从环境变量获取密钥
    api_key = os.getenv("OPENAI_API_KEY")
    api_base = os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    
    if not api_key:
        print("请设置 OPENAI_API_KEY 环境变量进行测试")
        return
    
    # 初始化服务
    qa_service = QAService(api_key, api_base)
    
    # 测试数据
    analysis_data = {
        'sentiment_distribution': {
            'positive': 150,
            'neutral': 200,
            'negative': 100
        },
        'trend_data': [
            {'date': '2024-01-01', 'positive': 20, 'neutral': 30, 'negative': 15},
            {'date': '2024-01-02', 'positive': 25, 'neutral': 35, 'negative': 18},
            {'date': '2024-01-03', 'positive': 30, 'neutral': 40, 'negative': 20}
        ],
        'top_words': [
            ['产品', 50],
            ['服务', 45],
            ['质量', 40],
            ['价格', 35],
            ['体验', 30]
        ]
    }
    
    print("=== 测试预定义问题 ===")
    qa_service.set_analysis_context(analysis_data)
    
    summary_response = await qa_service.ask_predefined_question('sentiment_summary')
    print(f"情感摘要: {summary_response.get('answer', 'No answer')}")

if __name__ == '__main__':
    import asyncio
    asyncio.run(test_qa_system())
