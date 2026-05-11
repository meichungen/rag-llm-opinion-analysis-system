# 情感分析模块
import os
import re
# Set Hugging Face Mirror
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

import torch
import torch.nn as nn
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from torch.optim import AdamW
from torch.utils.data import DataLoader, Dataset
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
import logging
import os
from datetime import datetime
import json

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SentimentDataset(Dataset):
    """情感分析数据集"""
    
    def __init__(self, texts: List[str], labels: List[int], tokenizer, max_length: int = 128):
        self.texts = texts
        self.labels = labels
        self.tokenizer = tokenizer
        self.max_length = max_length
    
    def __len__(self):
        return len(self.texts)
    
    def __getitem__(self, idx):
        text = str(self.texts[idx])
        label = self.labels[idx]
        
        encoding = self.tokenizer(
            text,
            truncation=True,
            padding='max_length',
            max_length=self.max_length,
            return_tensors='pt'
        )
        
        return {
            'text': text,
            'input_ids': encoding['input_ids'].flatten(),
            'attention_mask': encoding['attention_mask'].flatten(),
            'label': torch.tensor(label, dtype=torch.long)
        }

# 全局模型缓存
_GLOBAL_MODEL = None
_GLOBAL_TOKENIZER = None

class SentimentAnalyzer:
    """情感分析器"""
    
    def __init__(self, model_path: str = None, device: str = None):
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.model_path = model_path or 'lxyuan/distilbert-base-multilingual-cased-sentiments-student'
        
        # 标签映射
        # lxyuan model mapping: {0: 'positive', 1: 'neutral', 2: 'negative'}
        self.label_map = {
            0: 'positive',
            1: 'neutral', 
            2: 'negative'
        }
        self.reverse_label_map = {v: k for k, v in self.label_map.items()}
        
        # 初始化模型和分词器
        self.tokenizer = None
        self.model = None
        self.load_model()
    
    def load_model(self):
        """加载预训练模型"""
        global _GLOBAL_MODEL, _GLOBAL_TOKENIZER
        
        try:
            # 如果全局模型已加载且路径一致（简化处理，假设路径一般不变），直接使用
            if _GLOBAL_MODEL is not None and _GLOBAL_TOKENIZER is not None:
                self.model = _GLOBAL_MODEL
                self.tokenizer = _GLOBAL_TOKENIZER
                self.model.to(self.device) # 确保在正确设备
                return

            # 确定模型路径
            model_name = self.model_path
            
            # 使用AutoTokenizer加载
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            # 如果有本地模型文件，加载本地模型
            if os.path.exists(model_name) and os.path.isfile(model_name) and model_name.endswith('.pt'):
                logger.info(f"Loading model from {model_name}")
                self.model = torch.load(model_name, map_location=self.device)
            else:
                # 使用预训练模型
                logger.info(f"Loading pre-trained model: {model_name}")
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    model_name
                )
                
            self.model.to(self.device)
            self.model.eval()
            
            # Update label map from config if available
            if hasattr(self.model.config, 'id2label') and self.model.config.id2label:
                logger.info(f"Using label map from model config: {self.model.config.id2label}")
                # Convert keys to int if they are strings
                self.label_map = {int(k): v for k, v in self.model.config.id2label.items()}
                self.reverse_label_map = {v: k for k, v in self.label_map.items()}
            
            # 更新全局缓存
            _GLOBAL_MODEL = self.model
            _GLOBAL_TOKENIZER = self.tokenizer
            
            logger.info("Model loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to load model: {str(e)}")
            raise e
    
    def predict(self, text: str) -> Dict:
        """预测单个文本的情感"""
        try:
            # 预处理文本
            text = self.preprocess_text(text)
            
            # 分词
            inputs = self.tokenizer(
                text,
                truncation=True,
                padding='max_length',
                max_length=128,
                return_tensors='pt'
            )
            
            # 移动到设备
            input_ids = inputs['input_ids'].to(self.device)
            attention_mask = inputs['attention_mask'].to(self.device)
            
            # 预测
            with torch.no_grad():
                outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
                logits = outputs.logits
                probabilities = torch.nn.functional.softmax(logits, dim=-1)
                prediction = torch.argmax(logits, dim=-1).item()
                confidence = probabilities[0][prediction].item()
            
            return {
                'text': text,
                'sentiment': self.label_map[prediction],
                'confidence': float(confidence),
                'probabilities': {
                    label: float(prob)
                    for label, prob in zip(['negative', 'neutral', 'positive'], probabilities[0])
                }
            }
            
        except Exception as e:
            logger.error(f"Prediction failed for text '{text}': {str(e)}")
            return {
                'text': text,
                'sentiment': 'neutral',
                'confidence': 0.0,
                'error': str(e)
            }
    
    def predict_batch(self, texts: List[str], batch_size: int = 32) -> List[Dict]:
        """批量预测文本情感"""
        results = []
        
        # 分批处理
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i + batch_size]
            batch_results = []
            
            for text in batch_texts:
                result = self.predict(text)
                batch_results.append(result)
            
            results.extend(batch_results)
            
            # 记录进度
            if (i + batch_size) % 100 == 0:
                logger.info(f"Processed {i + batch_size}/{len(texts)} texts")
        
        logger.info(f"Batch prediction completed for {len(texts)} texts")
        return results
    
    def preprocess_text(self, text: str) -> str:
        """文本预处理"""
        if not text:
            return ""
        
        # 移除HTML标签
        text = re.sub(r'<[^>]+>', '', text)
        
        # 移除多余的空白字符
        text = re.sub(r'\s+', ' ', text)
        
        # 移除特殊字符和表情符号（保留中文、英文、数字和基本标点）
        text = re.sub(r'[^\u4e00-\u9fff\u0041-\u005a\u0061-\u007a\u0030-\u0039\u3000-\u303f\uff00-\uffef\s.,!?;:()""''-]', '', text)
        
        # 去除首尾空格
        text = text.strip()
        
        return text
    
    def train_model(self, train_texts: List[str], train_labels: List[str], 
                   val_texts: List[str] = None, val_labels: List[str] = None,
                   epochs: int = 3, batch_size: int = 16, learning_rate: float = 2e-5):
        """训练模型"""
        
        logger.info("Starting model training")
        
        # 转换标签
        train_labels_idx = [self.reverse_label_map[label] for label in train_labels]
        
        # 创建数据集
        train_dataset = SentimentDataset(train_texts, train_labels_idx, self.tokenizer)
        train_dataloader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        
        # 验证集
        val_dataloader = None
        if val_texts and val_labels:
            val_labels_idx = [self.reverse_label_map[label] for label in val_labels]
            val_dataset = SentimentDataset(val_texts, val_labels_idx, self.tokenizer)
            val_dataloader = DataLoader(val_dataset, batch_size=batch_size)
        
        # 优化器
        optimizer = AdamW(self.model.parameters(), lr=learning_rate)
        
        # 损失函数
        criterion = nn.CrossEntropyLoss()
        
        # 训练循环
        self.model.train()
        for epoch in range(epochs):
            total_loss = 0
            correct = 0
            total = 0
            
            for batch in train_dataloader:
                input_ids = batch['input_ids'].to(self.device)
                attention_mask = batch['attention_mask'].to(self.device)
                labels = batch['label'].to(self.device)
                
                # 前向传播
                outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
                logits = outputs.logits
                
                # 计算损失
                loss = criterion(logits, labels)
                
                # 反向传播
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
                # 统计
                total_loss += loss.item()
                _, predicted = torch.max(logits, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
            
            accuracy = 100 * correct / total
            avg_loss = total_loss / len(train_dataloader)
            
            logger.info(f"Epoch {epoch + 1}/{epochs} - Loss: {avg_loss:.4f}, Accuracy: {accuracy:.2f}%")
            
            # 验证
            if val_dataloader:
                val_accuracy = self.evaluate(val_dataloader)
                logger.info(f"Validation Accuracy: {val_accuracy:.2f}%")
        
        logger.info("Model training completed")
    
    def evaluate(self, dataloader: DataLoader) -> float:
        """评估模型"""
        self.model.eval()
        correct = 0
        total = 0
        
        with torch.no_grad():
            for batch in dataloader:
                input_ids = batch['input_ids'].to(self.device)
                attention_mask = batch['attention_mask'].to(self.device)
                labels = batch['label'].to(self.device)
                
                outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
                logits = outputs.logits
                
                _, predicted = torch.max(logits, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()
        
        accuracy = 100 * correct / total
        return accuracy
    
    def save_model(self, path: str):
        """保存模型"""
        try:
            torch.save(self.model, path)
            logger.info(f"Model saved to {path}")
        except Exception as e:
            logger.error(f"Failed to save model: {str(e)}")
            raise e
    
    def get_model_info(self) -> Dict:
        """获取模型信息"""
        return {
            'model_name': self.model_path,
            'num_labels': 3,
            'labels': ['negative', 'neutral', 'positive'],
            'device': self.device,
            'model_version': '1.0.0',
            'created_at': datetime.now().isoformat()
        }


class SentimentAnalysisService:
    """情感分析服务"""
    
    def __init__(self, model_path: str = None):
        self.analyzer = SentimentAnalyzer(model_path)
        self.stats = {
            'total_processed': 0,
            'sentiment_counts': {'positive': 0, 'neutral': 0, 'negative': 0}
        }
    
    def analyze_comments(self, comments: List[Dict], task_id: int = None) -> List[Dict]:
        """分析评论情感"""
        if not comments:
            return []
        
        logger.info(f"Starting sentiment analysis for {len(comments)} comments")
        
        # 提取评论文本
        texts = [comment.get('content', '') for comment in comments]
        
        # 批量预测
        results = self.analyzer.predict_batch(texts, batch_size=32)
        
        # 更新统计
        self.stats['total_processed'] += len(comments)
        for result in results:
            sentiment = result['sentiment']
            self.stats['sentiment_counts'][sentiment] += 1
        
        # 添加评论ID到结果中
        for i, result in enumerate(results):
            if i < len(comments):
                result['comment_id'] = comments[i].get('id')
                result['task_id'] = task_id
        
        logger.info(f"Sentiment analysis completed")
        return results
    
    def get_sentiment_stats(self) -> Dict:
        """获取情感分析统计"""
        return {
            'total_processed': self.stats['total_processed'],
            'sentiment_distribution': self.stats['sentiment_counts'],
            'percentages': {
                sentiment: count / max(self.stats['total_processed'], 1) * 100
                for sentiment, count in self.stats['sentiment_counts'].items()
            }
        }
    
    def generate_report(self, results: List[Dict]) -> Dict:
        """生成分析报告"""
        if not results:
            return {'error': 'No results to analyze'}
        
        # 统计情感分布
        sentiment_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
        confidence_scores = {'positive': [], 'neutral': [], 'negative': []}
        
        for result in results:
            sentiment = result['sentiment']
            confidence = result['confidence']
            
            sentiment_counts[sentiment] += 1
            confidence_scores[sentiment].append(confidence)
        
        # 计算平均置信度
        avg_confidence = {
            sentiment: np.mean(scores) if scores else 0
            for sentiment, scores in confidence_scores.items()
        }
        
        # 生成报告
        total = len(results)
        report = {
            'summary': {
                'total_comments': total,
                'sentiment_distribution': sentiment_counts,
                'percentages': {
                    sentiment: count / total * 100
                    for sentiment, count in sentiment_counts.items()
                },
                'average_confidence': avg_confidence
            },
            'insights': self.generate_insights(sentiment_counts, avg_confidence),
            'generated_at': datetime.now().isoformat()
        }
        
        return report
    
    def generate_insights(self, sentiment_counts: Dict, avg_confidence: Dict) -> List[str]:
        """生成洞察"""
        insights = []
        
        total = sum(sentiment_counts.values())
        if total == 0:
            return insights
        
        # 主导情感
        dominant_sentiment = max(sentiment_counts, key=sentiment_counts.get)
        dominant_percentage = sentiment_counts[dominant_sentiment] / total * 100
        
        insights.append(f"主导情感为{dominant_sentiment}，占比{dominant_percentage:.1f}%")
        
        # 情感平衡分析
        if sentiment_counts['positive'] > sentiment_counts['negative']:
            insights.append("正面情感多于负面情感，整体情感倾向积极")
        elif sentiment_counts['negative'] > sentiment_counts['positive']:
            insights.append("负面情感多于正面情感，需要关注用户反馈")
        else:
            insights.append("正面和负面情感相对平衡")
        
        # 置信度分析
        avg_conf = np.mean(list(avg_confidence.values()))
        if avg_conf > 0.8:
            insights.append("模型置信度较高，分析结果可信")
        elif avg_conf > 0.6:
            insights.append("模型置信度中等，建议结合人工审核")
        else:
            insights.append("模型置信度较低，需要人工验证")
        
        return insights


# 测试函数
def test_sentiment_analysis():
    """测试情感分析功能"""
    
    # 测试文本
    test_texts = [
        "这个产品真的很棒，我非常满意！",
        "一般般，没什么特别的。",
        "质量太差了，完全不值这个价钱。",
        "服务态度很好，物流也很快。",
        "有点失望，和预期差距较大。",
        "超出预期，会推荐给朋友。",
        "还可以吧，中规中矩。",
        "非常糟糕的体验，不会再买了。"
    ]
    
    # 初始化分析器
    analyzer = SentimentAnalyzer()
    
    print("=== 单文本测试 ===")
    for text in test_texts[:3]:
        result = analyzer.predict(text)
        print(f"文本: {text}")
        print(f"情感: {result['sentiment']}, 置信度: {result['confidence']:.3f}")
        print(f"概率分布: {result['probabilities']}")
        print()
    
    print("=== 批量测试 ===")
    results = analyzer.predict_batch(test_texts)
    
    # 统计结果
    sentiment_counts = {'positive': 0, 'neutral': 0, 'negative': 0}
    for result in results:
        sentiment_counts[result['sentiment']] += 1
    
    print(f"情感分布统计:")
    for sentiment, count in sentiment_counts.items():
        percentage = count / len(results) * 100
        print(f"{sentiment}: {count} ({percentage:.1f}%)")
    
    print("\n=== 服务测试 ===")
    service = SentimentAnalysisService()
    
    # 模拟评论数据
    comments = [
        {'id': i, 'content': text}
        for i, text in enumerate(test_texts)
    ]
    
    results = service.analyze_comments(comments)
    report = service.generate_report(results)
    
    print("分析报告:")
    print(f"总评论数: {report['summary']['total_comments']}")
    print(f"情感分布: {report['summary']['sentiment_distribution']}")
    print(f"洞察: {report['insights']}")


if __name__ == '__main__':
    test_sentiment_analysis()