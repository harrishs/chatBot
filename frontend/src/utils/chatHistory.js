export function buildChatHistory(messages = [], chatbotId) {
        const history = [];
        if (!Number.isFinite(chatbotId)) {
                return history;
        }

        for (let index = 0; index < messages.length; index += 1) {
                const userMessage = messages[index];
                if (!userMessage || userMessage.role !== "user") {
                        continue;
                }

                const assistantMessage = messages[index + 1];
                if (!assistantMessage || assistantMessage.role !== "assistant") {
                        continue;
                }

                history.push({
                        chatbot_id: chatbotId,
                        user: userMessage.content ?? "",
                        assistant: assistantMessage.content ?? "",
                });

                index += 1;
        }

        return history;
}

export function buildChatRequest({ id, messages = [], query }) {
        const chatbotId = Number(id);
        return {
                url: `/chatbots/${id}/chat/`,
                body: {
                        query,
                        history: buildChatHistory(messages, chatbotId),
                },
        };
}
