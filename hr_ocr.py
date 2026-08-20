import os
import traceback
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")


def analyser_image_api(image_path: str) -> str:
    """Envoie l'image à l'API Inference Hugging Face via le SDK officiel."""
    if not HF_API_KEY:
        print("❌ Erreur : La clé HF_API_KEY est introuvable sur Render.")
        return ""

    try:
        # Initialisation du client Inference officiel
        client = InferenceClient(token=HF_API_KEY)

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        print("🚀 Appel API Cloud (Hugging Face SDK)...")

        # Utilisation de l'API de description/texte d'image
        # Si trocr-base-handwritten pose problème, utiliser 'naver-clova-ix/donut-base'
        response = client.image_to_text(
            image=image_bytes, model="microsoft/trocr-base-handwritten"
        )

        texte_predit = str(response).strip()
        print(f"✅ HTR Réussi : '{texte_predit}'")
        return texte_predit

    except Exception as e:
        print(f"❌ Erreur Hugging Face [{type(e).__name__}] : {e}")
        # Affiche la trace complète dans les logs Render pour cibler la ligne
        traceback.print_exc()
        return ""