import os
import requests

# Apuntamos al secreto personalizado que acabas de crear
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URLmacro")

def enviar_actualizacion_discord(mensaje):
    if not WEBHOOK_URL:
        raise ValueError("No se encontró la URL del Webhook en las variables de entorno.")
    
    payload = {
        "content": mensaje
    }
    
    response = requests.post(WEBHOOK_URL, json=payload)
    if response.status_code == 204:
        print("¡Actualización enviada con éxito a Discord!")
    else:
        print(f"Error al enviar: {response.status_code}, {response.text}")

if __name__ == "__main__":
    mensaje_institucional = """
📊 **ACTUALIZACIÓN DIARIA INSTITUCIONAL (DCM) — EUR/USD**

> **1. 👁 Fase Pre-Evento (Enfoque Táctico)**
> * **Contexto & Soft Data:** El flujo mantiene la inercia bajista ante la resiliencia económica de EE. UU. frente a Europa.
> * **Lectura COT:** Fondos institucionales con cortos masivos (-63,256 contratos); cualquier rebote técnico se gestiona estrictamente como un retroceso correctivo.
> * **Traducción en el Gráfico:** Esperamos el barrido de liquidez en la zona alta (`$$$`) previa a las actas del FOMC del miércoles para buscar el rechazo bajista alineado con el flujo institucional.

*El sistema actualizará el estado conforme nos acerquemos al evento y tras su publicación.*
    """
    
    enviar_actualizacion_discord(mensaje_institucional)
