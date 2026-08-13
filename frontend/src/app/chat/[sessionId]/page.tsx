import { ChatWorkspace } from "@/components/ChatWorkspace";

export default async function ChatSessionPage(
  props: PageProps<"/chat/[sessionId]">,
) {
  const { sessionId } = await props.params;
  const parsed = Number(sessionId);

  // A non-numeric id never reaches the socket; the workspace shows its empty
  // state instead, and the server would refuse it in any case.
  return (
    <ChatWorkspace sessionId={Number.isInteger(parsed) ? parsed : null} />
  );
}
