export const FEEDBACK_PREFIX = "/feedback";

export function extractFeedbackComment(input = "") {
        const trimmed = input.trim();
        if (!trimmed.startsWith(FEEDBACK_PREFIX)) {
                return null;
        }

        return trimmed.slice(FEEDBACK_PREFIX.length).trim();
}

export async function submitFeedbackComment({ apiClient, chatbotId, comment }) {
        const url = `/chatbots/${chatbotId}/chat/`;
        const response = await apiClient.post(url, {
                query: FEEDBACK_PREFIX,
                comment,
        });

        const data = response?.data ?? {};
        return {
                message: data.message ?? data.detail ?? "Thanks for your feedback!",
        };
}

export async function processFeedbackCommand({
        trimmedQuery,
        apiClient,
        chatbotId,
        setNotice,
        setQuery,
}) {
        const feedbackComment = extractFeedbackComment(trimmedQuery);
        if (feedbackComment === null) {
                return false;
        }

        if (!feedbackComment) {
                setNotice("Please provide feedback after /feedback.");
                return true;
        }

        try {
                const { message } = await submitFeedbackComment({
                        apiClient,
                        chatbotId,
                        comment: feedbackComment,
                });
                setNotice(message);
        } catch (error) {
                console.error("Feedback error:", error);
                setNotice("Unable to submit feedback. Please try again.");
        } finally {
                setQuery("");
        }

        return true;
}
