import os
import re

docs_dir = r"D:\Python Projects\simulato\docs"

replacements = [
    # API Keys to GCP Config
    (r"GROK_API_KEY(=| )", r"GCP_PROJECT_ID\1"),
    (r"GEMINI_API_KEY(=| )", r"GCP_LOCATION\1"),
    (r"your-grok-api-key-here", r"your-gcp-project-id"),
    (r"your-gemini-api-key-here", r"us-central1"),
    (r"your_key_here", r"your-gcp-project-id"),
    (r"GROK_API_KEY or GEMINI_API_KEY", r"GCP_PROJECT_ID and GCP_LOCATION"),
    (r"API keys in `\.env` for both Gemini and Grok", r"Application Default Credentials (ADC) and project settings"),

    # AI Provider / Model Names
    (r"Cloud Grok API", r"Vertex AI Gemini"),
    (r"Grok Vision API", r"Vertex AI Gemini"),
    (r"Grok/Gemini", r"Vertex AI Gemini"),
    (r"Grok and Gemini", r"Vertex AI Gemini"),
    (r"Grok Cloud", r"Vertex AI"),
    (r"Cloud Grok", r"Vertex AI"),
    (r"Grok Vision", r"Vertex AI Gemini"),
    (r"Grok API", r"Vertex AI API"),
    (r"Grok", r"Gemini"), # Fallback for remaining Grok references
    (r"gemini-exp-1206", r"gemini-2.5-flash"),
    (r"grok-2-vision-1212", r"gemini-2.5-flash"),

    # Client/Code structure
    (r"grok_client(\.py)?", r"gemini_client\1"),
    (r"GrokResponse", r"AIResponse"),
    (r"parse_grok_response", r"parse_ai_response"),

    # Remote Commands
    (r"SET_AI_PROVIDER(?: command)?", r""),
    (r"Runtime AI Provider Switching: `SET_AI_PROVIDER`.*", r"Runtime AI Provider Switching: Removed (Vertex AI is exclusive)"),
    (r"Default AI provider: `DEFAULT_AI_PROVIDER`.*", r"Default AI provider: Enforced Vertex AI (Gemini 2.5 Flash)"),
]

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    new_content = content
    for old, new in replacements:
        new_content = re.sub(old, new, new_content, flags=re.IGNORECASE)
        
    # Manual cleanups for specific files
    if "COMMUNICATION_PROTOCOLS.md" in filepath:
        # Remove the SET_AI_PROVIDER example block
        new_content = re.sub(r"Example — switching cloud AI provider.*?takes effect[^\.]*\.", "", new_content, flags=re.DOTALL | re.IGNORECASE)
    
    if "SETUP_GUIDE.md" in filepath:
        new_content = re.sub(r"# Pick one or both cloud AI providers:[\s\S]*?GCP_LOCATION=us-central1\n", "# Vertex AI Configuration:\nGCP_PROJECT_ID=your-gcp-project-id\nGCP_LOCATION=us-central1\n", new_content)

    if content != new_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Updated {os.path.basename(filepath)}")

for filename in os.listdir(docs_dir):
    if filename.endswith(".md"):
        process_file(os.path.join(docs_dir, filename))
