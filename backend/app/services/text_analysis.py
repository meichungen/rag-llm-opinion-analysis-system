import jieba
from collections import Counter
from typing import List, Dict, Any
import logging
import numpy as np
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation
import re
import os

logger = logging.getLogger(__name__)

class TextAnalysisService:
    def __init__(self, stop_words_path: str = None):
        self.stop_words = set()
        if not stop_words_path:
            # Default to the one in app directory
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            stop_words_path = os.path.join(current_dir, 'stop_words.txt')
            
        if os.path.exists(stop_words_path):
            try:
                with open(stop_words_path, 'r', encoding='utf-8') as f:
                    self.stop_words = set(line.strip() for line in f if line.strip())
                logger.info(f"Loaded {len(self.stop_words)} stop words for text analysis")
            except Exception as e:
                logger.error(f"Failed to load stop words: {e}")

    def clean_text(self, text: str) -> str:
        if not text:
            return ""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        # Remove URLs
        text = re.sub(r'http[s]?://\S+', '', text)
        # Keep only Chinese, English and numbers
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
        return text.strip()

    def generate_word_cloud_data(self, texts: List[str], top_n: int = 100) -> List[Dict[str, Any]]:
        """Generate word frequency data for word cloud"""
        all_words = []
        for text in texts:
            cleaned = self.clean_text(text)
            if not cleaned:
                continue
            words = jieba.cut(cleaned)
            filtered = [
                word for word in words 
                if len(word) > 1 and word not in self.stop_words and not word.isspace()
            ]
            all_words.extend(filtered)
        
        counter = Counter(all_words)
        return [{"name": word, "value": count} for word, count in counter.most_common(top_n)]

    def perform_lda_analysis(self, texts: List[str], n_topics: int = 5, n_keywords: int = 10) -> List[Dict[str, Any]]:
        """Perform LDA topic modeling using scikit-learn"""
        if len(texts) < n_topics:
            return []

        # Preprocess texts: segment and remove stop words
        processed_docs = []
        for text in texts:
            cleaned = self.clean_text(text)
            if not cleaned:
                continue
            words = jieba.cut(cleaned)
            filtered = " ".join([
                word for word in words 
                if len(word) > 1 and word not in self.stop_words and not word.isspace()
            ])
            if filtered:
                processed_docs.append(filtered)

        if not processed_docs:
            return []

        try:
            # Vectorize text
            tf_vectorizer = CountVectorizer(max_df=0.95, min_df=2, stop_words=None) # Stop words handled manually
            tf = tf_vectorizer.fit_transform(processed_docs)
            
            if tf.shape[1] == 0:
                return []

            # LDA model
            lda = LatentDirichletAllocation(
                n_components=n_topics, 
                max_iter=10, 
                learning_method='online',
                random_state=42
            )
            lda.fit(tf)

            # Extract topics and keywords
            feature_names = tf_vectorizer.get_feature_names_out()
            topics = []
            
            for topic_idx, topic in enumerate(lda.components_):
                top_features_ind = topic.argsort()[:-n_keywords - 1:-1]
                keywords = [
                    {"name": feature_names[i], "weight": float(topic[i])} 
                    for i in top_features_ind
                ]
                topics.append({
                    "id": topic_idx,
                    "keywords": keywords
                })
            
            return topics
        except Exception as e:
            logger.error(f"LDA analysis failed: {e}")
            return []
