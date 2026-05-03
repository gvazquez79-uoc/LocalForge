import type { Message } from "../api/client";

interface Props {
  message: Message;
}

export const MessageBubble: React.FC<Props> = ({ message }) => {
  const isUser = message.role === "user";

  return (
    <div style={{
      display: "flex",
      justifyContent: isUser ? "flex-end" : "flex-start",
      marginBottom: 8,
      padding: "0 4px",
    }}>
      {!isUser && (
        <div style={{
          width: 28, height: 28, borderRadius: 8, flexShrink: 0,
          background: "linear-gradient(135deg, #10b981, #059669)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, marginRight: 8, alignSelf: "flex-end",
        }}>
          🔨
        </div>
      )}

      <div style={{
        maxWidth: "78%",
        background: isUser ? "#10b981" : "#1c1c1e",
        borderRadius: isUser ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
        padding: "10px 14px",
        border: isUser ? "none" : "1px solid #2c2c2e",
      }}>
        <pre style={{
          margin: 0,
          fontFamily: "inherit",
          fontSize: 14,
          lineHeight: 1.5,
          color: isUser ? "#fff" : "#e4e4e7",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {message.content || (
            <span style={{ opacity: 0.4, fontStyle: "italic" }}>Pensando…</span>
          )}
        </pre>
      </div>
    </div>
  );
};
