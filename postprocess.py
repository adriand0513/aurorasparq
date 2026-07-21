# postprocess.py

import re

def clean_reply(text: str) -> str:
    if not text:
        return "Hey..."
    
    # Only remove hyphens/dashes
    text = re.sub(r'[-—–]', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)  # clean up extra spaces
    
    return text.strip()


def split_into_bubbles(text: str, max_chars: int = 220) -> list:
    """Basic bubble splitting (kept so main.py doesn't break)"""
    if not text:
        return []
    
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    
    bubbles = []
    current = ""
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        if len(current) + len(sentence) + 1 > max_chars and current:
            bubbles.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip() if current else sentence
    
    if current:
        bubbles.append(current.strip())
    
    return bubbles
