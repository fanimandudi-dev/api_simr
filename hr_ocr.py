import os
import traceback
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")


def analyser_image_api(image_path: str) -> str:
    if not HF_API_KEY:
        print(
            "❌ Erreur : La clé HF_API_KEY est introuvable ou vide dans l'environnement Render."
        )
        return ""

    try:
        client = InferenceClient(token=HF_API_KEY)

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        print("🚀 Appel API Cloud (Hugging Face SDK)...")

        response = client.image_to_text(
            image=image_bytes, model="microsoft/trocr-base-handwritten"
        )

        texte_predit = str(response).strip()
        print(f"✅ HTR Réussi : '{texte_predit}'")
        return texte_predit

    except Exception as e:
        # Affiche le type d'erreur exact + le détail du problème
        print(f"❌ Erreur lors de l'appel Hugging Face [{type(e).__name__}] : {repr(e)}")
        # Utile dans les logs Render pour voir la ligne exacte qui plante :
        traceback.print_exc()
        return ""