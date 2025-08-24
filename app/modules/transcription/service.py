from typing import Dict, List, Optional, Tuple
import groq
import json
import re
import math
from collections import Counter

from app.core.config import settings

# Common English stopwords for all keyword extraction methods
COMMON_STOPWORDS = set([
    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 
    "you're", "you've", "you'll", "you'd", 'your', 'yours', 'yourself', 
    'yourselves', 'he', 'him', 'his', 'himself', 'she', "she's", 'her', 
    'hers', 'herself', 'it', "it's", 'its', 'itself', 'they', 'them', 
    'their', 'theirs', 'themselves', 'what', 'which', 'who', 'whom', 
    'this', 'that', "that'll", 'these', 'those', 'am', 'is', 'are', 'was', 
    'were', 'be', 'been', 'being', 'have', 'has', 'had', 'having', 'do', 
    'does', 'did', 'doing', 'a', 'an', 'the', 'and', 'but', 'if', 'or', 
    'because', 'as', 'until', 'while', 'of', 'at', 'by', 'for', 'with', 
    'about', 'against', 'between', 'into', 'through', 'during', 'before', 
    'after', 'above', 'below', 'to', 'from', 'up', 'down', 'in', 'out', 
    'on', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here',
    'there', 'when', 'where', 'why', 'how', 'all', 'any', 'both', 'each', 'few',
    'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
    'same', 'so', 'than', 'too', 'very', 's', 't', 'can', 'will', 'just', 'don',
    'should', 'now', 'd', 'll', 'm', 'o', 're', 've', 'y', 'ain', 'aren', 'couldn',
    'didn', 'doesn', 'hadn', 'hasn', 'haven', 'isn', 'ma', 'mightn', 'mustn',
    'needn', 'shan', 'shouldn', 'wasn', 'weren', 'won', 'wouldn'
])

# Custom stopwords for call transcriptions
CALL_STOPWORDS = {
    'call', 'hello', 'hi', 'yes', 'no', 'okay', 'ok', 'um', 'uh', 'er', 
    'hmm', 'thank', 'thanks', 'please', 'bye', 'goodbye', 'agent', 'user'
}

# Groq-based analysis functions
def _call_groq_api(groq_client: groq.Groq, system_prompt: str, user_prompt: str, 
                  temperature: float = 0.1, max_tokens: int = 100) -> Optional[dict]:
    """Helper function to call Groq API with error handling"""
    try:
        response = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens
        )
        
        response_content = response.choices[0].message.content
        return json.loads(response_content)
    except json.JSONDecodeError as e:
        print(f"Error parsing Groq response: {e}")
    except Exception as e:
        print(f"Error calling Groq API: {e}")
    
    return None


def make_transcription_readable(groq_client: groq.Groq, content: str) -> str:
    """Convert raw transcription into a more readable Q&A format using Groq"""
    system_prompt = "You are a transcription formatting assistant."
    user_prompt = f"""
    You are a transcription formatter.
I will provide you with a raw call transcription between an agent and a customer.

Your tasks are:

Format the transcription into a Question–Answer style (Agent vs. Customer).

Clean up filler words/repetitions while keeping the meaning intact.

Ensure the output reads like a clear dialogue script with alternating lines.

Do not add or remove information—just structure it for readability.
Also Make it json formatted arrays of question and answers
    
    Raw Transcription:
    {content}
    
    Formatted Transcription:
    """
    
    result = _call_groq_api(groq_client, system_prompt, user_prompt,max_tokens=10000)
    
    if result:
        try:
            # Assuming the Groq response is a JSON array of Q&A pairs
            formatted_transcription = json.dumps(result, indent=2)
            return formatted_transcription
        except (ValueError, TypeError) as e:
            print(f"Error processing formatted transcription result: {e}")
            return ""
    return ""

def analyze_sentiment(groq_client: groq.Groq, content: str) -> Tuple[str, float]:
    """Analyze sentiment of transcription using Groq"""
    system_prompt = "You are a sentiment analysis assistant that returns JSON only."
    user_prompt = f"""
    Analyze the sentiment of the following call transcription between a user and an agent.
    Return a JSON object with two fields:
    1. 'sentiment': The overall sentiment (positive, negative, or neutral)
    2. 'score': A score from -1 (very negative) to 1 (very positive)
    
    Transcription:
    {content}
    
    JSON response:
    """
    
    result = _call_groq_api(groq_client, system_prompt, user_prompt, temperature=0.1, max_tokens=100)
    
    if result:
        try:
            sentiment = result.get("sentiment", "neutral")
            score = float(result.get("score", 0.0))
            return sentiment, score
        except (ValueError, TypeError) as e:
            print(f"Error processing sentiment result: {e}")
    
    # Fallback to neutral sentiment if Groq fails
    return "neutral", 0.0

def rate_call(groq_client: groq.Groq, content: str) -> Tuple[int, str]:
    """Rate the call out of 10 using Groq"""
    system_prompt = "You are a call quality assessment assistant that returns JSON only."
    user_prompt = f"""
    Rate the following call transcription between a user and an agent on a scale of 1 to 10.
    Consider factors like professionalism, helpfulness, clarity, and resolution.
    Return a JSON object with two fields:
    1. 'rating': An integer score from 1 to 10
    2. 'explanation': A brief explanation for the rating
    
    Transcription:
    {content}
    
    JSON response:
    """
    
    result = _call_groq_api(groq_client, system_prompt, user_prompt, temperature=0.2, max_tokens=200)
    
    if result:
        try:
            rating = int(result.get("rating", 5))
            # Ensure rating is within bounds
            rating = max(1, min(10, rating))
            explanation = result.get("explanation", "")
            return rating, explanation
        except (ValueError, TypeError) as e:
            print(f"Error processing rating result: {e}")
    
    # Fallback to default rating if Groq fails
    return 5, "Unable to generate detailed rating explanation"


def get_client_details(groq_client: groq.Groq, content: str) -> Dict[str, str]:
    """Extract client details from transcription using Groq"""
    system_prompt = "You are a client details extraction assistant that returns JSON only."
    user_prompt = f"""
    Extract client details from the following call transcription.
    Return a JSON object with the following fields:
    1. 'name': Client's name
    2. 'email': Client's email address
    
    Transcription:
    {content}
    
    JSON response:
    """
    
    result = _call_groq_api(groq_client, system_prompt, user_prompt, temperature=0.1, max_tokens=150)
    
    if result:
        try:
            return {
                "name": result.get("name", ""),
                "email": result.get("email", "")
            }
        except (ValueError, TypeError) as e:
            print(f"Error processing client details result: {e}")
    
    # Fallback to empty details if Groq fails
    return {"name": "", "email": ""}



def extract_keywords(groq_client: groq.Groq, content: str) -> Dict[str, int]:
    """Extract keywords from text content
    
    Args:
        groq_client: Groq client instance (not used in current implementation)
        content: Text content to extract keywords from
        
    Returns:
        Dictionary of keywords with their frequencies
    """
    # Use TF-IDF based keyword extraction instead of LLM
    return tfidf_keyword_extraction(content)

def basic_keyword_extraction(content: str) -> Dict[str, int]:
    """Keyword extraction using NLTK for lemmatization
    
    Args:
        content: Text content to extract keywords from
        
    Returns:
        Dictionary of keywords with their frequencies
    """
    try:
        import nltk
        from nltk.corpus import stopwords
        from nltk.stem import WordNetLemmatizer
        
        # Download necessary NLTK resources with error handling
        for resource in ['stopwords', 'wordnet']:
            try:
                nltk.download(resource, quiet=True)
            except Exception as e:
                print(f"Error downloading NLTK resource {resource}: {e}")
                return fallback_keyword_extraction(content)
        
        # Initialize lemmatizer
        lemmatizer = WordNetLemmatizer()
        
        # Get stopwords (combine NLTK stopwords with our common stopwords)
        try:
            nltk_stopwords = set(stopwords.words('english'))
            stop_words = COMMON_STOPWORDS.union(nltk_stopwords).union(CALL_STOPWORDS)
        except Exception as e:
            print(f"Error getting NLTK stopwords: {e}")
            # Use our predefined stopwords if NLTK stopwords fail
            stop_words = COMMON_STOPWORDS.union(CALL_STOPWORDS)
        
        # Simple tokenization using regex instead of word_tokenize
        tokens = re.findall(r'\b[a-zA-Z]{3,}\b', content.lower())
        
        # Remove stopwords
        filtered_tokens = [word for word in tokens if word not in stop_words]
        
        # Lemmatize tokens
        try:
            lemmatized_tokens = [lemmatizer.lemmatize(word) for word in filtered_tokens]
        except Exception as e:
            print(f"Error lemmatizing: {e}")
            lemmatized_tokens = filtered_tokens
        
        # Count frequencies
        word_counts = Counter(lemmatized_tokens)
        
        # Return top 20 keywords
        return dict(word_counts.most_common(20))
    
    except ImportError as e:
        print(f"NLTK import error: {e}")
        return fallback_keyword_extraction(content)
    
    except Exception as e:
        # Fallback if any other error occurs
        print(f"Error in NLTK keyword extraction: {e}")
        return fallback_keyword_extraction(content)

def tfidf_keyword_extraction(content: str) -> Dict[str, int]:
    """Lightweight TF-IDF based keyword extraction without external libraries
    
    Args:
        content: Text content to extract keywords from
        
    Returns:
        Dictionary of keywords with their frequencies
    """
    # Use combined stopwords from constants
    stop_words = COMMON_STOPWORDS.union(CALL_STOPWORDS)
    
    # Split content into sentences (simple approach)
    sentences = re.split(r'[.!?]\s+', content.lower())
    sentences = [s for s in sentences if s.strip()]
    
    # Tokenize each sentence
    tokenized_sentences = []
    for sentence in sentences:
        # Extract words with at least 3 characters
        words = re.findall(r'\b[a-zA-Z]{3,}\b', sentence)
        # Filter out stopwords
        filtered_words = [word for word in words if word not in stop_words]
        tokenized_sentences.append(filtered_words)
    
    # Calculate term frequency (TF) for each word in the document
    all_words = [word for sentence in tokenized_sentences for word in sentence]
    
    # Handle empty content or content with only stopwords
    if not all_words:
        return {}
        
    tf = Counter(all_words)
    
    # Calculate inverse document frequency (IDF)
    word_in_sentences = {}
    for word in set(all_words):
        word_in_sentences[word] = sum(1 for sentence in tokenized_sentences if word in sentence)
    
    # Calculate TF-IDF scores
    tfidf_scores = {}
    num_sentences = max(1, len(sentences))  # Avoid division by zero
    
    for word, count in tf.items():
        # Skip words that appear in only one sentence (likely not significant)
        # But only if we have enough sentences to make this meaningful
        if word_in_sentences[word] <= 1 and num_sentences > 3:
            continue
        
        # TF = word count / total words in document
        term_freq = count / len(all_words)
        
        # IDF = log(total sentences / number of sentences containing the word)
        inverse_doc_freq = math.log(num_sentences / max(1, word_in_sentences[word]))
        
        # TF-IDF score
        tfidf_scores[word] = term_freq * inverse_doc_freq
    
    # Sort by TF-IDF score and convert to frequency format for compatibility
    sorted_words = sorted(tfidf_scores.items(), key=lambda x: x[1], reverse=True)[:20]
    
    # Convert to the expected format (word -> frequency)
    # Using the original term frequency for consistency with other functions
    result = {word: tf[word] for word, _ in sorted_words}
    
    return result

def fallback_keyword_extraction(content: str) -> Dict[str, int]:
    """Very basic keyword extraction without any external libraries
    
    This is the simplest implementation used as a fallback when other methods fail.
    It uses regex for tokenization and a predefined list of stopwords.
    
    Args:
        content: Text content to extract keywords from
        
    Returns:
        Dictionary of keywords with their frequencies (top 20)
    """
    # Use combined stopwords from constants
    stop_words = COMMON_STOPWORDS.union(CALL_STOPWORDS)
    
    # Handle empty content
    if not content or not content.strip():
        return {}
    
    # Simple tokenization with regex
    words = re.findall(r'\b[a-zA-Z]{3,}\b', content.lower())
    
    # Filter out stopwords
    filtered_words = [word for word in words if word not in stop_words]
    
    # Handle case where all words are stopwords
    if not filtered_words:
        return {}
    
    # Count word frequencies
    word_counts = Counter(filtered_words)
    
    # Return top 20 keywords
    return dict(word_counts.most_common(20))
                          
                         
        
        
        
        
        
        
