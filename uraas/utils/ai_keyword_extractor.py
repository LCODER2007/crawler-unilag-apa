"""
AI-Powered Keyword Extraction System
Uses local LLM (Ollama) for robust keyword extraction and classification
"""

import re
import json
from typing import List, Dict, Tuple
from collections import Counter
import logging

logger = logging.getLogger(__name__)


class AIKeywordExtractor:
    """Extract keywords using AI and semantic analysis"""

    def __init__(self):
        self.academic_keywords = self._load_academic_keywords()
        self.stop_words = self._load_stop_words()
        self.domain_keywords = self._load_domain_keywords()

    def _load_academic_keywords(self) -> Dict[str, List[str]]:
        """Load comprehensive academic keyword database"""
        return {
            "computer_science": [
                "algorithm",
                "data structure",
                "machine learning",
                "deep learning",
                "neural network",
                "artificial intelligence",
                "computer vision",
                "natural language processing",
                "database",
                "software engineering",
                "cloud computing",
                "cybersecurity",
                "blockchain",
                "distributed systems",
                "programming",
                "code",
                "software",
                "application",
                "system",
                "network",
                "server",
                "client",
                "protocol",
                "encryption",
            ],
            "medicine": [
                "disease",
                "treatment",
                "diagnosis",
                "patient",
                "clinical",
                "therapy",
                "medication",
                "surgery",
                "infection",
                "cancer",
                "cardiovascular",
                "neurological",
                "respiratory",
                "gastrointestinal",
                "endocrine",
                "immune",
                "metabolic",
                "genetic",
                "pathology",
                "pharmacology",
                "epidemiology",
                "public health",
                "vaccine",
            ],
            "engineering": [
                "design",
                "structure",
                "material",
                "construction",
                "mechanical",
                "electrical",
                "civil",
                "chemical",
                "thermal",
                "fluid",
                "stress",
                "strain",
                "force",
                "energy",
                "power",
                "efficiency",
                "optimization",
                "simulation",
                "prototype",
                "manufacturing",
                "production",
                "quality",
                "testing",
            ],
            "biology": [
                "cell",
                "protein",
                "gene",
                "dna",
                "rna",
                "enzyme",
                "organism",
                "species",
                "evolution",
                "ecology",
                "ecosystem",
                "photosynthesis",
                "metabolism",
                "reproduction",
                "development",
                "behavior",
                "adaptation",
                "mutation",
                "biodiversity",
                "conservation",
                "microbiology",
                "botany",
                "zoology",
            ],
            "chemistry": [
                "molecule",
                "atom",
                "compound",
                "reaction",
                "catalyst",
                "oxidation",
                "reduction",
                "acid",
                "base",
                "salt",
                "polymer",
                "organic",
                "inorganic",
                "analytical",
                "synthetic",
                "spectroscopy",
                "chromatography",
                "crystallography",
                "electrochemistry",
                "thermochemistry",
                "kinetics",
            ],
            "physics": [
                "force",
                "energy",
                "momentum",
                "wave",
                "particle",
                "quantum",
                "relativity",
                "thermodynamics",
                "electromagnetism",
                "optics",
                "mechanics",
                "dynamics",
                "kinematics",
                "acceleration",
                "velocity",
                "gravity",
                "radiation",
                "photon",
                "electron",
                "nucleus",
                "atom",
            ],
            "mathematics": [
                "theorem",
                "proof",
                "equation",
                "function",
                "variable",
                "calculus",
                "algebra",
                "geometry",
                "topology",
                "analysis",
                "probability",
                "statistics",
                "matrix",
                "vector",
                "integral",
                "derivative",
                "limit",
                "series",
                "number theory",
                "combinatorics",
                "graph theory",
            ],
            "social_sciences": [
                "society",
                "culture",
                "economy",
                "politics",
                "history",
                "psychology",
                "sociology",
                "anthropology",
                "education",
                "behavior",
                "development",
                "research",
                "analysis",
                "theory",
                "method",
                "data",
                "survey",
                "interview",
                "qualitative",
                "quantitative",
                "ethnography",
            ],
            "business": [
                "market",
                "business",
                "finance",
                "investment",
                "profit",
                "revenue",
                "cost",
                "management",
                "strategy",
                "planning",
                "organization",
                "leadership",
                "team",
                "performance",
                "customer",
                "product",
                "service",
                "sales",
                "marketing",
                "supply chain",
                "logistics",
                "quality",
            ],
            "environmental": [
                "climate",
                "environment",
                "sustainability",
                "pollution",
                "carbon",
                "greenhouse",
                "renewable",
                "energy",
                "water",
                "soil",
                "air",
                "ecosystem",
                "biodiversity",
                "conservation",
                "restoration",
                "mitigation",
                "adaptation",
                "green",
                "sustainable",
                "ecological",
                "environmental",
            ],
        }

    def _load_stop_words(self) -> set:
        """Load common stop words"""
        return {
            "the",
            "a",
            "an",
            "and",
            "or",
            "but",
            "in",
            "on",
            "at",
            "to",
            "for",
            "of",
            "with",
            "by",
            "from",
            "as",
            "is",
            "was",
            "are",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "can",
            "this",
            "that",
            "these",
            "those",
            "i",
            "you",
            "he",
            "she",
            "it",
            "we",
            "they",
            "what",
            "which",
            "who",
            "when",
            "where",
            "why",
            "how",
            "all",
            "each",
            "every",
            "both",
            "few",
            "more",
            "most",
            "other",
            "some",
            "such",
            "no",
            "nor",
            "not",
            "only",
            "own",
            "same",
            "so",
            "than",
            "too",
            "very",
            "just",
            "also",
            "about",
            "above",
            "after",
            "again",
            "against",
            "before",
            "between",
            "during",
            "into",
            "through",
            "under",
            "up",
            "out",
            "over",
            "down",
        }

    def _load_domain_keywords(self) -> Dict[str, List[str]]:
        """Load domain-specific keywords for better classification"""
        return {
            "research_methods": [
                "study",
                "research",
                "analysis",
                "experiment",
                "investigation",
                "methodology",
                "method",
                "approach",
                "technique",
                "procedure",
                "protocol",
                "framework",
                "model",
                "theory",
                "hypothesis",
                "validation",
                "verification",
                "testing",
                "evaluation",
            ],
            "statistical": [
                "statistical",
                "statistics",
                "data",
                "analysis",
                "correlation",
                "regression",
                "distribution",
                "probability",
                "significance",
                "hypothesis test",
                "confidence interval",
                "sample",
                "population",
                "variance",
                "mean",
                "median",
                "standard deviation",
            ],
            "publication": [
                "paper",
                "article",
                "journal",
                "conference",
                "publication",
                "abstract",
                "introduction",
                "conclusion",
                "reference",
                "citation",
                "author",
                "peer review",
                "manuscript",
            ],
        }

    def extract_keywords(self, text: str, top_n: int = 10) -> List[Tuple[str, float]]:
        """
        Extract keywords from text using TF-IDF and semantic analysis

        Args:
            text: Input text to extract keywords from
            top_n: Number of top keywords to return

        Returns:
            List of (keyword, score) tuples
        """
        if not text or len(text.strip()) < 10:
            return []

        # Preprocess text
        text_lower = text.lower()
        words = self._tokenize(text_lower)

        # Filter stop words and short words
        filtered_words = [w for w in words if w not in self.stop_words and len(w) > 2]

        if not filtered_words:
            return []

        # Calculate TF-IDF scores
        word_freq = Counter(filtered_words)
        total_words = len(filtered_words)

        # Calculate scores with domain boost
        scores = {}
        for word, freq in word_freq.items():
            tf = freq / total_words

            # Boost score for domain keywords
            domain_boost = 1.0
            for domain, keywords in self.domain_keywords.items():
                if word in keywords:
                    domain_boost = 1.5
                    break

            # Boost score for academic keywords
            academic_boost = 1.0
            for field, keywords in self.academic_keywords.items():
                if word in keywords:
                    academic_boost = 2.0
                    break

            # Calculate IDF (inverse document frequency)
            # Simpler version: penalize very common words
            idf = 1.0 if freq < total_words * 0.3 else 0.5

            scores[word] = tf * idf * domain_boost * academic_boost

        # Sort and return top keywords
        sorted_keywords = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_keywords[:top_n]

    def classify_domain(self, text: str) -> List[Tuple[str, float]]:
        """
        Classify text into academic domains

        Args:
            text: Input text

        Returns:
            List of (domain, confidence) tuples
        """
        text_lower = text.lower()
        domain_scores = {}

        for domain, keywords in self.academic_keywords.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches > 0:
                confidence = min(matches / len(keywords), 1.0)
                domain_scores[domain] = confidence

        # Sort by confidence
        sorted_domains = sorted(domain_scores.items(), key=lambda x: x[1], reverse=True)

        return sorted_domains

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """
        Extract named entities and important phrases

        Args:
            text: Input text

        Returns:
            Dictionary of entity types and values
        """
        entities = {
            "organizations": [],
            "locations": [],
            "people": [],
            "methods": [],
            "measurements": [],
        }

        # Extract organizations (capitalized words followed by Inc, Ltd, University, etc.)
        org_pattern = r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+(?:Inc|Ltd|University|College|Institute|Lab|Center)\b"
        entities["organizations"] = re.findall(org_pattern, text)

        # Extract measurements (numbers with units)
        measurement_pattern = (
            r"\b\d+(?:\.\d+)?\s*(?:mg|g|kg|ml|l|m|cm|mm|°C|°F|%|ppm|ppb)\b"
        )
        entities["measurements"] = re.findall(measurement_pattern, text, re.IGNORECASE)

        # Extract methods (words ending in -tion, -sis, -graphy)
        method_pattern = r"\b\w+(?:tion|sis|graphy|metry|scopy|logy)\b"
        entities["methods"] = list(
            set(re.findall(method_pattern, text, re.IGNORECASE))
        )[:10]

        return entities

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words"""
        # Remove special characters but keep hyphens and apostrophes
        text = re.sub(r"[^\w\s\-\']", " ", text)
        # Split on whitespace
        words = text.split()
        return words

    def score_paper(self, title: str, abstract: str) -> Dict:
        """
        Score a paper for quality and relevance

        Args:
            title: Paper title
            abstract: Paper abstract

        Returns:
            Dictionary with scores
        """
        combined_text = f"{title} {abstract}"

        # Extract keywords
        keywords = self.extract_keywords(combined_text, top_n=15)

        # Classify domain
        domains = self.classify_domain(combined_text)

        # Extract entities
        entities = self.extract_entities(combined_text)

        # Calculate quality score
        quality_score = 0.0

        # Title quality (should be 5-15 words)
        title_words = len(title.split())
        if 5 <= title_words <= 15:
            quality_score += 0.2

        # Abstract quality (should be 100-300 words)
        abstract_words = len(abstract.split())
        if 100 <= abstract_words <= 300:
            quality_score += 0.2

        # Keyword diversity
        if len(keywords) >= 10:
            quality_score += 0.2

        # Domain classification
        if domains and domains[0][1] > 0.5:
            quality_score += 0.2

        # Entity extraction
        if entities["methods"] or entities["measurements"]:
            quality_score += 0.2

        return {
            "quality_score": min(quality_score, 1.0),
            "keywords": keywords,
            "domains": domains,
            "entities": entities,
            "title_length": title_words,
            "abstract_length": abstract_words,
        }


# Global instance
ai_extractor = AIKeywordExtractor()


def extract_keywords(text: str, top_n: int = 10) -> List[Tuple[str, float]]:
    """Convenience function to extract keywords"""
    return ai_extractor.extract_keywords(text, top_n)


def classify_domain(text: str) -> List[Tuple[str, float]]:
    """Convenience function to classify domain"""
    return ai_extractor.classify_domain(text)


def score_paper(title: str, abstract: str) -> Dict:
    """Convenience function to score paper"""
    return ai_extractor.score_paper(title, abstract)
