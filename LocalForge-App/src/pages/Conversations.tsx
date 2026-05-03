import { useEffect, useState } from "react";
import {
  IonPage, IonHeader, IonToolbar, IonTitle, IonContent,
  IonList, IonItem, IonLabel, IonButton, IonIcon, IonButtons,
  IonMenuButton, IonItemSliding, IonItemOptions, IonItemOption,
  IonRefresher, IonRefresherContent, IonText, IonSpinner,
} from "@ionic/react";
import { addOutline, trashOutline, chatbubbleOutline } from "ionicons/icons";
import { listConversations, getConversation, deleteConversation } from "../api/client";
import { useAppStore } from "../store/app";
import { useIonRouter } from "@ionic/react";
import type { Message } from "../api/client";

export const Conversations: React.FC = () => {
  const [loading, setLoading]   = useState(true);
  const router                  = useIonRouter();
  const conversations           = useAppStore(s => s.conversations);
  const setConversations        = useAppStore(s => s.setConversations);
  const setActiveConvId         = useAppStore(s => s.setActiveConvId);
  const setMessages             = useAppStore(s => s.setMessages);

  const load = async () => {
    try {
      const data = await listConversations();
      setConversations(data.sort((a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      ));
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  const openConv = async (id: string) => {
    try {
      const data = await getConversation(id);
      setActiveConvId(id);
      setMessages(data.messages as Message[]);
      router.push("/chat");
    } catch { /* ignore */ }
  };

  const newChat = () => {
    setActiveConvId(null);
    setMessages([]);
    router.push("/chat");
  };

  const delConv = async (id: string) => {
    await deleteConversation(id);
    setConversations(conversations.filter(c => c.id !== id));
  };

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    if (diff < 60_000) return "ahora";
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h`;
    return d.toLocaleDateString("es", { day: "numeric", month: "short" });
  };

  return (
    <IonPage>
      <IonHeader>
        <IonToolbar style={{ "--background": "#1c1c1e", "--color": "#fff" }}>
          <IonButtons slot="start">
            <IonMenuButton style={{ color: "#10b981" }} />
          </IonButtons>
          <IonTitle>Conversaciones</IonTitle>
          <IonButtons slot="end">
            <IonButton onClick={newChat} style={{ "--color": "#10b981" }}>
              <IonIcon icon={addOutline} style={{ fontSize: 24 }} />
            </IonButton>
          </IonButtons>
        </IonToolbar>
      </IonHeader>

      <IonContent style={{ "--background": "#0f0f0f" }}>
        <IonRefresher slot="fixed" onIonRefresh={async (e) => { await load(); e.detail.complete(); }}>
          <IonRefresherContent />
        </IonRefresher>

        {loading ? (
          <div style={{ display: "flex", justifyContent: "center", paddingTop: 40 }}>
            <IonSpinner style={{ color: "#10b981" }} />
          </div>
        ) : conversations.length === 0 ? (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", height: "70%", gap: 12, opacity: 0.5,
          }}>
            <IonIcon icon={chatbubbleOutline} style={{ fontSize: 48, color: "#52525b" }} />
            <IonText style={{ color: "#71717a", fontSize: 14 }}>Sin conversaciones</IonText>
            <IonButton onClick={newChat} fill="outline" style={{ "--color": "#10b981", "--border-color": "#10b981" }}>
              Nueva conversación
            </IonButton>
          </div>
        ) : (
          <IonList style={{ background: "transparent", padding: "8px 0" }}>
            {conversations.map(conv => (
              <IonItemSliding key={conv.id}>
                <IonItem
                  button
                  detail={false}
                  onClick={() => openConv(conv.id)}
                  style={{
                    "--background": "#1c1c1e",
                    "--background-activated": "#2c2c2e",
                    "--border-color": "#2c2c2e",
                    "--padding-start": "16px",
                    marginBottom: 4,
                    borderRadius: 12,
                    overflow: "hidden",
                  }}
                >
                  <IonIcon
                    icon={chatbubbleOutline}
                    slot="start"
                    style={{ color: "#10b981", fontSize: 20 }}
                  />
                  <IonLabel>
                    <h2 style={{ color: "#fff", fontSize: 14, fontWeight: 500, margin: "0 0 2px" }}>
                      {conv.title || "Sin título"}
                    </h2>
                    <p style={{ color: "#71717a", fontSize: 12, margin: 0 }}>
                      {formatDate(conv.updated_at)}
                    </p>
                  </IonLabel>
                </IonItem>
                <IonItemOptions side="end">
                  <IonItemOption color="danger" onClick={() => delConv(conv.id)}>
                    <IonIcon icon={trashOutline} />
                  </IonItemOption>
                </IonItemOptions>
              </IonItemSliding>
            ))}
          </IonList>
        )}
      </IonContent>
    </IonPage>
  );
};
