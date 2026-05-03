import pandas as pd
import re
from typing import List, Tuple

def validate_domain(domain: str) -> bool:
    """
    Validate that the URL is a root domain.
    Matches domains like 'example.com', 'sub.example.co.uk'.
    Does not allow paths, protocols, or trailing slashes.
    """
    pattern = r'^[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,63}$'
    return bool(re.match(pattern, domain.lower()))

def read_key_domains(file_path: str) -> Tuple[List[str], str]:
    """
    Read Key_domains.csv and return a list of competitor domains and the client domain.
    """
    df = pd.read_csv(file_path)
    
    # Clean whitespace
    df['domain'] = df['domain'].str.strip()
    df['role'] = df['role'].str.strip().str.lower()
    
    # Validate domains
    invalid_domains = df[~df['domain'].apply(validate_domain)]
    if not invalid_domains.empty:
        raise ValueError(f"Invalid root domains found: {invalid_domains['domain'].tolist()}")
        
    competitors = df[df['role'] == 'competitor']['domain'].tolist()
    clients = df[df['role'] == 'client']['domain'].tolist()
    
    if not clients:
        raise ValueError("No client domain found in Key_domains.csv")
    
    return competitors, clients[0]
