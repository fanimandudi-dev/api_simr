import os
from dotenv import load_dotenv
from huggingface_hub import InferenceClient

load_dotenv()
HF_API_KEY = os.getenv("HF_API_KEY")


def analyser_image_api(image_path: str) -> str:
    if not HF_API_KEY:
        print("❌ Erreur : HF_API_KEY manquante.")
        return ""

    try:
        # InferenceClient gère automatiquement le routage correct des providers
        client = InferenceClient(token=HF_API_KEY)

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        print("🚀 Appel API Cloud (Hugging Face SDK)...")

        # Utilisation de la tâche image-to-text
        response = client.image_to_text(
            image=image_bytes, model="microsoft/trocr-base-handwritten"
        )

        # Si le SDK renvoie une chaîne directe ou un objet
        texte_predit = response.strip() if isinstance(response, str) else str(response)
        print(f"✅ HTR Réussi : '{texte_predit}'")
        return texte_predit

    except Exception as e:
        print(f"❌ Erreur lors de l'appel Hugging Face : {e}")
        return ""