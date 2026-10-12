import { Maximize2, RotateCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useUi } from "@/state/ui";
import { Drawer } from "@/components/ui";
import { ChatView } from "./ChatView";
import { useChat } from "./useChat";

export function ChatDrawer() {
  const { chatOpen, closeChat, chatSeed } = useUi();
  const chat = useChat();
  const nav = useNavigate();
  return (
    <Drawer
      open={chatOpen}
      onOpenChange={(v) => !v && closeChat()}
      width="max-w-2xl"
      title={
        <span className="flex items-center gap-2">
          Assistant
          <button type="button" className="btn-ghost text-xs" onClick={chat.reset} title="New conversation"><RotateCcw className="h-3.5 w-3.5" /></button>
          <button type="button" className="btn-ghost text-xs" onClick={() => { closeChat(); nav("/assistant"); }} title="Open the full page"><Maximize2 className="h-3.5 w-3.5" /></button>
        </span>
      }
    >
      <div className="h-full" data-testid="chat-drawer">
        <ChatView chat={chat} compact seed={chatOpen ? chatSeed : null} />
      </div>
    </Drawer>
  );
}
