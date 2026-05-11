# 数据可视化模块
import json
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import logging
from wordcloud import WordCloud
import jieba
from collections import Counter
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
import base64

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

class DataVisualizer:
    """数据可视化器"""
    
    def __init__(self):
        self.colors = {
            'positive': '#52c41a',  # 绿色
            'neutral': '#faad14',   # 橙色
            'negative': '#f5222d',  # 红色
            'primary': '#1890ff',   # 蓝色
            'secondary': '#722ed1'  # 紫色
        }
        
        # 停用词列表
        self.stop_words = {
            '的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个',
            '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好',
            '自己', '这', '那', '就是', '啊', '吧', '吗', '呢', '哦', '嗯', '哈哈', '哈哈哈'
        }
    
    def create_sentiment_pie_chart(self, sentiment_data: Dict) -> Dict:
        """创建情感分布饼图"""
        try:
            # 准备数据
            labels = []
            sizes = []
            colors = []
            
            for sentiment, count in sentiment_data.items():
                labels.append(self.get_sentiment_label(sentiment))
                sizes.append(count)
                colors.append(self.colors.get(sentiment, '#999999'))
            
            # 创建图表
            fig, ax = plt.subplots(figsize=(8, 8))
            
            wedges, texts, autotexts = ax.pie(
                sizes,
                labels=labels,
                colors=colors,
                autopct='%1.1f%%',
                startangle=90,
                textprops={'fontsize': 12}
            )
            
            # 设置标题
            ax.set_title('情感分布', fontsize=16, fontweight='bold', pad=20)
            
            # 美化
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
            
            # 转换为base64
            chart_data = self.fig_to_base64(fig)
            plt.close(fig)
            
            return {
                'type': 'pie',
                'title': '情感分布',
                'data': chart_data,
                'statistics': sentiment_data
            }
            
        except Exception as e:
            logger.error(f"Failed to create sentiment pie chart: {str(e)}")
            return {'error': str(e)}
    
    def create_sentiment_trend_chart(self, trend_data: List[Dict]) -> Dict:
        """创建情感趋势折线图"""
        try:
            # 准备数据
            df = pd.DataFrame(trend_data)
            
            if df.empty:
                return {'error': 'No trend data available'}
            
            # 转换日期格式
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date')
            
            # 创建图表
            fig, ax = plt.subplots(figsize=(12, 6))
            
            # 绘制各情感趋势线
            sentiments = ['positive', 'neutral', 'negative']
            for sentiment in sentiments:
                if sentiment in df.columns:
                    ax.plot(
                        df['date'],
                        df[sentiment],
                        marker='o',
                        linewidth=2,
                        label=self.get_sentiment_label(sentiment),
                        color=self.colors.get(sentiment, '#999999')
                    )
            
            # 设置图表属性
            ax.set_title('情感趋势变化', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('日期', fontsize=12)
            ax.set_ylabel('数量', fontsize=12)
            ax.legend()
            ax.grid(True, alpha=0.3)
            
            # 旋转日期标签
            plt.xticks(rotation=45)
            plt.tight_layout()
            
            # 转换为base64
            chart_data = self.fig_to_base64(fig)
            plt.close(fig)
            
            return {
                'type': 'line',
                'title': '情感趋势',
                'data': chart_data,
                'trend_data': trend_data
            }
            
        except Exception as e:
            logger.error(f"Failed to create sentiment trend chart: {str(e)}")
            return {'error': str(e)}
    
    def create_word_cloud(self, texts: List[str], max_words: int = 100) -> Dict:
        """创建词云"""
        try:
            if not texts:
                return {'error': 'No text data available'}
            
            # 文本预处理
            processed_texts = []
            for text in texts:
                if text and isinstance(text, str):
                    # 使用jieba分词
                    words = jieba.cut(text)
                    # 过滤停用词和短词
                    filtered_words = [
                        word for word in words 
                        if len(word) > 1 and word not in self.stop_words
                    ]
                    processed_texts.extend(filtered_words)
            
            if not processed_texts:
                return {'error': 'No valid words found'}
            
            # 统计词频
            word_freq = Counter(processed_texts)
            
            # 创建词云
            wordcloud = WordCloud(
                width=800,
                height=600,
                background_color='white',
                max_words=max_words,
                font_path='simhei.ttf',  # 中文字体
                colormap='viridis'
            ).generate_from_frequencies(word_freq)
            
            # 创建图表
            fig, ax = plt.subplots(figsize=(10, 8))
            ax.imshow(wordcloud, interpolation='bilinear')
            ax.axis('off')
            ax.set_title('热点词云', fontsize=16, fontweight='bold', pad=20)
            
            # 转换为base64
            chart_data = self.fig_to_base64(fig)
            plt.close(fig)
            
            # 获取热词列表
            top_words = word_freq.most_common(20)
            
            return {
                'type': 'wordcloud',
                'title': '热点词云',
                'data': chart_data,
                'top_words': top_words
            }
            
        except Exception as e:
            logger.error(f"Failed to create word cloud: {str(e)}")
            return {'error': str(e)}
    
    def create_sentiment_bar_chart(self, sentiment_data: Dict) -> Dict:
        """创建情感分布柱状图"""
        try:
            # 准备数据
            labels = [self.get_sentiment_label(sentiment) for sentiment in sentiment_data.keys()]
            values = list(sentiment_data.values())
            colors = [self.colors.get(sentiment, '#999999') for sentiment in sentiment_data.keys()]
            
            # 创建图表
            fig, ax = plt.subplots(figsize=(10, 6))
            
            bars = ax.bar(labels, values, color=colors, alpha=0.8)
            
            # 添加数值标签
            for bar in bars:
                height = bar.get_height()
                ax.text(
                    bar.get_x() + bar.get_width() / 2.,
                    height + max(values) * 0.01,
                    f'{int(height)}',
                    ha='center',
                    va='bottom',
                    fontsize=10
                )
            
            # 设置图表属性
            ax.set_title('情感分布统计', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('情感类型', fontsize=12)
            ax.set_ylabel('数量', fontsize=12)
            ax.grid(True, alpha=0.3, axis='y')
            
            plt.tight_layout()
            
            # 转换为base64
            chart_data = self.fig_to_base64(fig)
            plt.close(fig)
            
            return {
                'type': 'bar',
                'title': '情感分布',
                'data': chart_data,
                'statistics': sentiment_data
            }
            
        except Exception as e:
            logger.error(f"Failed to create sentiment bar chart: {str(e)}")
            return {'error': str(e)}
    
    def create_confidence_distribution_chart(self, confidence_data: List[float]) -> Dict:
        """创建置信度分布图"""
        try:
            if not confidence_data:
                return {'error': 'No confidence data available'}
            
            # 创建图表
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # 绘制直方图
            n, bins, patches = ax.hist(
                confidence_data,
                bins=20,
                alpha=0.7,
                color=self.colors['primary'],
                edgecolor='black'
            )
            
            # 设置图表属性
            ax.set_title('置信度分布', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('置信度', fontsize=12)
            ax.set_ylabel('频次', fontsize=12)
            ax.grid(True, alpha=0.3)
            
            # 添加统计信息
            mean_conf = np.mean(confidence_data)
            std_conf = np.std(confidence_data)
            
            stats_text = f'平均值: {mean_conf:.3f}\n标准差: {std_conf:.3f}\n样本数: {len(confidence_data)}'
            ax.text(
                0.02, 0.98, stats_text,
                transform=ax.transAxes,
                verticalalignment='top',
                bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5)
            )
            
            plt.tight_layout()
            
            # 转换为base64
            chart_data = self.fig_to_base64(fig)
            plt.close(fig)
            
            return {
                'type': 'histogram',
                'title': '置信度分布',
                'data': chart_data,
                'statistics': {
                    'mean': float(mean_conf),
                    'std': float(std_conf),
                    'count': len(confidence_data)
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to create confidence distribution chart: {str(e)}")
            return {'error': str(e)}
    
    def create_comprehensive_dashboard(self, data: Dict) -> Dict:
        """创建综合分析仪表板"""
        try:
            # 创建大图
            fig = plt.figure(figsize=(16, 12))
            
            # 子图布局
            gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
            
            # 1. 情感分布饼图
            if 'sentiment_distribution' in data:
                ax1 = fig.add_subplot(gs[0, 0])
                sentiment_data = data['sentiment_distribution']
                labels = [self.get_sentiment_label(s) for s in sentiment_data.keys()]
                sizes = list(sentiment_data.values())
                colors = [self.colors.get(s, '#999999') for s in sentiment_data.keys()]
                
                ax1.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
                ax1.set_title('情感分布', fontsize=12)
            
            # 2. 情感趋势图
            if 'trend_data' in data:
                ax2 = fig.add_subplot(gs[0, 1:])
                trend_data = data['trend_data']
                if trend_data:
                    df = pd.DataFrame(trend_data)
                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date')
                    
                    for sentiment in ['positive', 'neutral', 'negative']:
                        if sentiment in df.columns:
                            ax2.plot(df['date'], df[sentiment], label=self.get_sentiment_label(sentiment),
                                   color=self.colors.get(sentiment, '#999999'))
                    
                    ax2.set_title('情感趋势', fontsize=12)
                    ax2.legend()
                    ax2.grid(True, alpha=0.3)
            
            # 3. 置信度分布
            if 'confidence_scores' in data:
                ax3 = fig.add_subplot(gs[1, 0])
                confidence_scores = data['confidence_scores']
                ax3.hist(confidence_scores, bins=20, alpha=0.7, color=self.colors['primary'])
                ax3.set_title('置信度分布', fontsize=12)
                ax3.set_xlabel('置信度')
                ax3.set_ylabel('频次')
            
            # 4. 词云
            if 'texts' in data:
                ax4 = fig.add_subplot(gs[1, 1:])
                texts = data['texts']
                if texts:
                    wordcloud = self.generate_wordcloud_object(texts)
                    ax4.imshow(wordcloud, interpolation='bilinear')
                    ax4.axis('off')
                    ax4.set_title('热点词云', fontsize=12)
            
            # 5. 统计信息
            ax5 = fig.add_subplot(gs[2, :])
            ax5.axis('off')
            
            # 生成统计文本
            stats_text = self.generate_stats_text(data)
            ax5.text(0.1, 0.9, stats_text, transform=ax5.transAxes,
                    fontsize=11, verticalalignment='top',
                    bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
            
            # 设置总标题
            fig.suptitle('社交媒体情感分析仪表板', fontsize=16, fontweight='bold')
            
            # 转换为base64
            chart_data = self.fig_to_base64(fig)
            plt.close(fig)
            
            return {
                'type': 'dashboard',
                'title': '综合分析仪表板',
                'data': chart_data,
                'charts': {
                    'sentiment_pie': '情感分布饼图',
                    'sentiment_trend': '情感趋势图',
                    'confidence_distribution': '置信度分布图',
                    'word_cloud': '热点词云'
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to create comprehensive dashboard: {str(e)}")
            return {'error': str(e)}
    
    def generate_wordcloud_object(self, texts: List[str]) -> WordCloud:
        """生成词云对象"""
        # 文本预处理
        processed_texts = []
        for text in texts:
            if text and isinstance(text, str):
                words = jieba.cut(text)
                filtered_words = [
                    word for word in words 
                    if len(word) > 1 and word not in self.stop_words
                ]
                processed_texts.extend(filtered_words)
        
        # 统计词频
        word_freq = Counter(processed_texts)
        
        # 创建词云
        wordcloud = WordCloud(
            width=800,
            height=400,
            background_color='white',
            max_words=100,
            font_path='simhei.ttf',
            colormap='viridis'
        ).generate_from_frequencies(word_freq)
        
        return wordcloud
    
    def generate_stats_text(self, data: Dict) -> str:
        """生成统计文本"""
        lines = []
        
        # 基本统计
        if 'sentiment_distribution' in data:
            total = sum(data['sentiment_distribution'].values())
            lines.append(f"📊 总样本数: {total}")
            
            for sentiment, count in data['sentiment_distribution'].items():
                percentage = count / total * 100 if total > 0 else 0
                lines.append(f"   {self.get_sentiment_label(sentiment)}: {count} ({percentage:.1f}%)")
        
        # 置信度统计
        if 'confidence_scores' in data:
            scores = data['confidence_scores']
            if scores:
                avg_conf = np.mean(scores)
                lines.append(f"\n🎯 平均置信度: {avg_conf:.3f}")
                lines.append(f"   最高置信度: {max(scores):.3f}")
                lines.append(f"   最低置信度: {min(scores):.3f}")
        
        # 时间范围
        if 'trend_data' in data and data['trend_data']:
            dates = [item['date'] for item in data['trend_data']]
            if dates:
                lines.append(f"\n📅 数据时间范围: {min(dates)} 至 {max(dates)}")
        
        # 模型信息
        if 'model_info' in data:
            model_info = data['model_info']
            lines.append(f"\n🤖 模型: {model_info.get('name', 'BERT')}")
            lines.append(f"   版本: {model_info.get('version', '1.0')}")
        
        return '\n'.join(lines)
    
    def get_sentiment_label(self, sentiment: str) -> str:
        """获取情感标签中文名称"""
        labels = {
            'positive': '正面',
            'neutral': '中性',
            'negative': '负面'
        }
        return labels.get(sentiment, sentiment)
    
    def fig_to_base64(self, fig) -> str:
        """将matplotlib图表转换为base64字符串"""
        buffer = BytesIO()
        fig.savefig(buffer, format='png', dpi=100, bbox_inches='tight')
        buffer.seek(0)
        
        image_base64 = base64.b64encode(buffer.getvalue()).decode()
        buffer.close()
        
        return f"data:image/png;base64,{image_base64}"


# 测试函数
def test_visualization():
    """测试可视化功能"""
    visualizer = DataVisualizer()
    
    # 测试数据
    sentiment_data = {
        'positive': 150,
        'neutral': 200,
        'negative': 100
    }
    
    trend_data = [
        {'date': '2024-01-01', 'positive': 20, 'neutral': 30, 'negative': 15},
        {'date': '2024-01-02', 'positive': 25, 'neutral': 35, 'negative': 18},
        {'date': '2024-01-03', 'positive': 30, 'neutral': 40, 'negative': 20},
        {'date': '2024-01-04', 'positive': 28, 'neutral': 38, 'negative': 22},
        {'date': '2024-01-05', 'positive': 35, 'neutral': 45, 'negative': 25}
    ]
    
    texts = [
        "这个产品真的很棒，我非常满意！",
        "服务态度很好，物流也很快。",
        "质量太差了，完全不值这个价钱。",
        "一般般，没什么特别的。",
        "超出预期，会推荐给朋友。",
        "有点失望，和预期差距较大。",
        "还可以吧，中规中矩。",
        "非常糟糕的体验，不会再买了。"
    ]
    
    confidence_scores = [0.95, 0.87, 0.92, 0.78, 0.85, 0.91, 0.73, 0.88]
    
    print("=== 测试情感分布饼图 ===")
    pie_result = visualizer.create_sentiment_pie_chart(sentiment_data)
    print(f"饼图生成成功: {pie_result['type']}")
    
    print("\n=== 测试情感趋势图 ===")
    trend_result = visualizer.create_sentiment_trend_chart(trend_data)
    print(f"趋势图生成成功: {trend_result['type']}")
    
    print("\n=== 测试词云 ===")
    wordcloud_result = visualizer.create_word_cloud(texts)
    print(f"词云生成成功: {wordcloud_result['type']}")
    
    print("\n=== 测试置信度分布 ===")
    confidence_result = visualizer.create_confidence_distribution_chart(confidence_scores)
    print(f"置信度分布图生成成功: {confidence_result['type']}")
    
    print("\n=== 测试综合仪表板 ===")
    dashboard_data = {
        'sentiment_distribution': sentiment_data,
        'trend_data': trend_data,
        'texts': texts,
        'confidence_scores': confidence_scores,
        'model_info': {
            'name': 'BERT',
            'version': '1.0.0'
        }
    }
    
    dashboard_result = visualizer.create_comprehensive_dashboard(dashboard_data)
    print(f"综合仪表板生成成功: {dashboard_result['type']}")


if __name__ == '__main__':
    test_visualization()