import { useEffect, useRef, useState, useCallback } from "react";
import {
  IonPage, IonHeader, IonToolbar, IonTitle, IonContent, IonFooter,
  IonTextarea, IonButton, IonIcon, IonSpinner, IonButtons,
  IonMenuButton,
} from "@ionic/react";
import { sendOutline, stopCircleOutline } from "ionicons/icons";
import {
  sendMessage, listModels, loadModel, saveModel, createConversation, approveTool,
} from "../api/client";
import { useAppStore } from "../store/app";
import { MessageBubble } from "../components/MessageBubble";
import { ModelPicker } from "../components/ModelPicker";

export const Chat: React.FC = () => {
  const [input, setInput]     = useState("");
  const contentRef            = useRef<HTMLIonContentElement>(null);
  const stopRef               = useRef<(() => void) | null>(null);

  const messages        = useAppStore(s => s.messages);
  const activeConvId    = useAppStore(s => s.activeConvId);
  const activeModel     = useAppStore(s => s.activeModel);
  const isStreaming     = useAppStore(s => s.isStreaming);
  const models          = useAppStore(s => s.models);
  const setModels       = useAppStore(s => s.setModels);
  const setActiveModel  = useAppStore(s => s.setActiveModel);
  const setActiveConvId = useAppStore(s => s.setActiveConvId);
  const addUserMessage  = useAppStore(s => s.addUserMessage);
  const startAssistant  = useAppStore(s => s.startAssistantMessage);
  const appendChunk     = useAppStore(s => s.appendChunk);
  const setStreaming    = useAppStore(s => s.setStreaming);

  // Load models once
  useEffect(() => {
    listModels().then(ms => {
      setModels(ms);
      const saved = loadModel();
      const def = ms.find(m => m.is_default) ?? ms[0];
      setActiveModel(saved && ms.find(m => m.name === saved) ? saved : def?.name ?? "");
    }).catch(() => {});
  }, []);

  // Auto-scroll
  useEffect(() => {
    setTimeout(() => contentRef.current?.scrollToBottom(200), 50);
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");

    addUserMessage(text);
    startAssistant();
    setStreaming(true);

    // Write the error into the pending assistant bubble rather than dropping it
    // — clearing the bubble first would leave appendChunk with nowhere to write.
    const fail = (err: string) => {
      appendChunk(`⚠️ Error: ${err}`);
      setStreaming(false);
      stopRef.current = null;
    };

    // The backend streams per conversation and keeps the history itself, so we
    // need a conversation id before sending the first message.
    let convId = activeConvId;
    if (!convId) {
      try {
        const conv = await createConversation(activeModel);
        convId = conv.id;
        setActiveConvId(convId);
      } catch (e) {
        fail(String(e instanceof Error ? e.message : e));
        return;
      }
    }
    const streamConvId = convId;

    stopRef.current = sendMessage(
      streamConvId,
      text,
      activeModel,
      (event) => {
        const data = (event.data ?? {}) as Record<string, unknown>;
        switch (event.type) {
          case "text_delta":
            appendChunk(String(data.text ?? ""));
            break;
          case "tool_call":
            appendChunk(`\n\n🔧 ${data.name ?? "tool"}\n`);
            break;
          case "tool_confirmation_needed":
            // There is no approval UI on mobile — decline so the agent loop
            // continues instead of blocking for its 5-minute timeout.
            appendChunk(
              `\n\n⚠️ La acción "${data.name ?? "?"}" requiere confirmación. ` +
              `Rechazada automáticamente: apruébala desde la interfaz web.\n`,
            );
            if (data.tool_use_id) {
              approveTool(streamConvId, String(data.tool_use_id), false).catch(() => {});
            }
            break;
          case "error":
            appendChunk(`\n\n⚠️ ${data.message ?? "Error desconocido"}\n`);
            break;
        }
      },
      () => {
        setStreaming(false);
        stopRef.current = null;
      },
      fail,
    );
  }, [input, isStreaming, activeModel, activeConvId]);

  const handleStop = () => {
    stopRef.current?.();
    stopRef.current = null;
    setStreaming(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <IonPage>
      <IonHeader>
        <IonToolbar style={{ "--background": "#1c1c1e", "--color": "#fff" }}>
          <IonButtons slot="start">
            <IonMenuButton style={{ color: "#10b981" }} />
          </IonButtons>
          <IonTitle style={{ fontSize: 16 }}>
            {activeConvId ? "Conversación" : "Nueva conversación"}
          </IonTitle>
          <IonButtons slot="end">
            <ModelPicker
              models={models}
              value={activeModel}
              onChange={(name) => { setActiveModel(name); saveModel(name); }}
            />
          </IonButtons>
        </IonToolbar>
      </IonHeader>

      <IonContent
        ref={contentRef}
        style={{ "--background": "#0f0f0f" }}
        scrollEvents
      >
        {messages.length === 0 ? (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center",
            justifyContent: "center", height: "100%", gap: 12, opacity: 0.5,
          }}>
            <div style={{ fontSize: 48 }}>🔨</div>
            <p style={{ color: "#71717a", margin: 0, fontSize: 14 }}>
              ¿En qué puedo ayudarte?
            </p>
          </div>
        ) : (
          <div style={{ padding: "12px 8px 8px" }}>
            {messages.map(msg => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
            {isStreaming && messages[messages.length - 1]?.content === "" && (
              <div style={{ display: "flex", gap: 6, padding: "8px 12px", alignItems: "center" }}>
                <IonSpinner name="dots" style={{ color: "#10b981", width: 20, height: 20 }} />
              </div>
            )}
          </div>
        )}
      </IonContent>

      <IonFooter style={{ background: "#1c1c1e", borderTop: "1px solid #2c2c2e" }}>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, padding: "8px 12px" }}>
          <IonTextarea
            value={input}
            onIonInput={e => setInput(e.detail.value ?? "")}
            onKeyDown={handleKeyDown}
            placeholder="Escribe un mensaje…"
            autoGrow
            rows={1}
            maxlength={8000}
            disabled={isStreaming}
            style={{
              flex: 1,
              "--background": "#2c2c2e",
              "--color": "#fff",
              "--placeholder-color": "#52525b",
              "--border-radius": "12px",
              "--padding-start": "12px",
              "--padding-end": "12px",
              "--padding-top": "10px",
              "--padding-bottom": "10px",
              fontSize: 15,
            }}
          />
          {isStreaming ? (
            <IonButton
              fill="clear"
              onClick={handleStop}
              style={{ "--color": "#ef4444", width: 44, height: 44 }}
            >
              <IonIcon icon={stopCircleOutline} style={{ fontSize: 26 }} />
            </IonButton>
          ) : (
            <IonButton
              fill="clear"
              onClick={handleSend}
              disabled={!input.trim()}
              style={{ "--color": "#10b981", width: 44, height: 44 }}
            >
              <IonIcon icon={sendOutline} style={{ fontSize: 22 }} />
            </IonButton>
          )}
        </div>
      </IonFooter>
    </IonPage>
  );
};
