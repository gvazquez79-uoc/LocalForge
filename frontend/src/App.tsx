import { Sidebar } from "./components/Sidebar";
import { ChatWindow } from "./components/ChatWindow";

export default function App() {
  return (
    <div className="flex h-screen bg-zinc-950 overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0">
        <ChatWindow />
      </main>
    </div>
  );
}
