import requests
import os
from dotenv import load_dotenv

load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")

# URL du modèle TrOCR spécialisé dans l'écriture manuscrite
API_URL = "https://api-inference.huggingface.co/models/microsoft/trocr-base-handwritten"
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}

def analyser_image_api(image_path: str) -> str:
    """
    Envoie l'image au modèle HTR Cloud et retourne le texte prédit.
    """
    if not HF_API_KEY:
        raise ValueError("Clé API Hugging Face introuvable dans le fichier .env")

    with open(image_path, "rb") as f:
        data = f.read()

    print("🚀 Appel API Cloud : Envoi au modèle TrOCR (Hugging Face)...")
    
    response = requests.post(API_URL, headers=HEADERS, data=data)
    
    if response.status_code == 200:
        result = response.json()
        if isinstance(result, list) and len(result) > 0 and 'generated_text' in result[0]:
            texte_predit = result[0]['generated_text']
            print(f"✅ HTR Réussi : '{texte_predit}'")
            return texte_predit
        return ""
    else:
        print(f"❌ Erreur API Hugging Face : {response.status_code} - {response.text}")
        return ""