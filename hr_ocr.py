import os
import time
import requests
from dotenv import load_dotenv

# Charge le fichier .env en local ; sur Render, os.getenv lira la variable du Dashboard
load_dotenv()

HF_API_KEY = os.getenv("HF_API_KEY")
# Remplacer microsoft/trocr-base-handwritten par un modèle supporté
API_URL = "https://router.huggingface.co/hf-inference/models/naver-clova-ix/donut-base"
HEADERS = {"Authorization": f"Bearer {HF_API_KEY}"}


def analyser_image_api(image_path: str) -> str:
    """Envoie l'image au modèle HTR Cloud sur Render et retourne le texte prédit."""
    if not HF_API_KEY:
        print("❌ Erreur : La clé HF_API_KEY est manquante dans l'environnement Render")
        return ""

    try:
        with open(image_path, "rb") as f:
            data = f.read()

        print("🚀 Appel API Cloud : Envoi au modèle TrOCR (Hugging Face)...")

        # Sur Render, on peut accorder 30s de timeout pour laisser le temps au modèle de répondre
        response = requests.post(API_URL, headers=HEADERS, data=data, timeout=30)

        # Si le modèle est en cours de démarrage (Cold Start), on réessaie 1 fois après 10s
        if response.status_code == 503:
            print("⏳ Modèle Hugging Face en cours de chargement... Attente de 10s puis réessai.")
            time.sleep(10)
            response = requests.post(API_URL, headers=HEADERS, data=data, timeout=30)

        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0 and "generated_text" in result[0]:
                texte_predit = result[0]["generated_text"]
                print(f"✅ HTR Réussi : '{texte_predit}'")
                return texte_predit
            return ""
        else:
            print(f"❌ Erreur API Hugging Face : {response.status_code} - {response.text}")
            return ""

    except requests.exceptions.Timeout:
        print("❌ Timeout : L'API Hugging Face a mis trop de temps à répondre.")
        return ""
    except requests.exceptions.RequestException as e:
        print(f"❌ Erreur de connexion sur le serveur Render : {e}")
        return ""