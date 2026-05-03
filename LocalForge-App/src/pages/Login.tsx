import { useState } from "react";
import {
  IonPage, IonContent, IonInput, IonButton, IonItem, IonLabel,
  IonSpinner, IonText, IonIcon,
} from "@ionic/react";
import { serverOutline, keyOutline } from "ionicons/icons";
import { checkHealth, saveServerConfig } from "../api/client";
import { useAppStore } from "../store/app";

export const Login: React.FC = () => {
  const [url, setUrl]       = useState("http://192.168.1.10:8000");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState("");
  const setLoggedIn = useAppStore(s => s.setLoggedIn);

  const handleConnect = async () => {
    setError("");
    setLoading(true);
    const trimmedUrl = url.trim().replace(/\/$/, "");
    saveServerConfig({ url: trimmedUrl, apiKey: apiKey.trim() });
    const ok = await checkHealth();
    if (ok) {
      setLoggedIn(true, trimmedUrl);
    } else {
      setError("No se pudo conectar. Verifica la URL y la API key.");
    }
    setLoading(false);
  };

  return (
    <IonPage>
      <IonContent className="ion-padding" style={{ "--background": "#0f0f0f" }}>
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", minHeight: "100%", gap: "24px",
        }}>
          {/* Logo */}
          <div style={{
            width: 72, height: 72, borderRadius: 18,
            background: "linear-gradient(135deg, #10b981, #059669)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 36, boxShadow: "0 8px 32px rgba(16,185,129,0.3)",
          }}>
            🔨
          </div>

          <div style={{ textAlign: "center" }}>
            <h1 style={{ color: "#fff", margin: 0, fontSize: 28, fontWeight: 700 }}>LocalForge</h1>
            <p style={{ color: "#71717a", margin: "4px 0 0", fontSize: 14 }}>Conecta con tu servidor</p>
          </div>

          {/* Form */}
          <div style={{
            width: "100%", maxWidth: 380,
            background: "#1c1c1e", borderRadius: 16, overflow: "hidden",
            border: "1px solid #2c2c2e",
          }}>
            <IonItem style={{ "--background": "transparent", "--border-color": "#2c2c2e" }}>
              <IonIcon icon={serverOutline} slot="start" style={{ color: "#10b981" }} />
              <IonLabel position="stacked" style={{ color: "#a1a1aa", fontSize: 12 }}>URL del servidor</IonLabel>
              <IonInput
                value={url}
                onIonInput={e => setUrl(e.detail.value ?? "")}
                placeholder="http://192.168.1.10:8000"
                style={{ "--color": "#fff", "--placeholder-color": "#52525b" }}
                inputmode="url"
                autocomplete="url"
              />
            </IonItem>

            <IonItem style={{ "--background": "transparent", "--border-color": "transparent" }}>
              <IonIcon icon={keyOutline} slot="start" style={{ color: "#10b981" }} />
              <IonLabel position="stacked" style={{ color: "#a1a1aa", fontSize: 12 }}>API Key (opcional)</IonLabel>
              <IonInput
                value={apiKey}
                onIonInput={e => setApiKey(e.detail.value ?? "")}
                placeholder="sk-..."
                type="password"
                style={{ "--color": "#fff", "--placeholder-color": "#52525b" }}
              />
            </IonItem>
          </div>

          {error && (
            <IonText color="danger" style={{ fontSize: 13, textAlign: "center" }}>
              {error}
            </IonText>
          )}

          <IonButton
            expand="block"
            onClick={handleConnect}
            disabled={loading || !url}
            style={{
              width: "100%", maxWidth: 380,
              "--background": "#10b981", "--background-activated": "#059669",
              "--border-radius": "12px", "--padding-top": "14px", "--padding-bottom": "14px",
              fontWeight: 600,
            }}
          >
            {loading ? <IonSpinner name="crescent" /> : "Conectar"}
          </IonButton>
        </div>
      </IonContent>
    </IonPage>
  );
};
