export const GIT_MISSING_CREDENTIAL_MESSAGE =
        "Please select a Git credential before adding the sync.";
export const GIT_SUBMIT_ERROR_MESSAGE =
        "Failed to create Git sync. Please check the configuration and try again.";

function deliverFeedback(notification, notifier, alertFn) {
        if (typeof notifier === "function") {
                notifier(notification);
        }

        const message =
                typeof notification === "string"
                        ? notification
                        : notification?.message;

        if (typeof alertFn === "function" && message) {
                alertFn(message);
        }
}

export async function handleGitSubmit({
        event,
        newGit,
        chatBotId,
        apiClient,
        notifier,
        alertFn,
        resetForm,
        reload,
        logError,
}) {
        event?.preventDefault?.();

        if (!newGit?.credential_id) {
                const notification = {
                        type: "error",
                        message: GIT_MISSING_CREDENTIAL_MESSAGE,
                };
                deliverFeedback(notification, notifier, alertFn);
                return {
                        success: false,
                        reason: "missing-credential",
                        ...(typeof notifier === "function" ? { notification } : {}),
                };
        }

        try {
                await apiClient.post(`/chatBots/${chatBotId}/gitRepoSyncs/`, {
                        ...newGit,
                        credential_id: parseInt(newGit.credential_id, 10),
                });
                if (typeof resetForm === "function") {
                        resetForm();
                }
                if (typeof reload === "function") {
                        await reload();
                }
                return { success: true };
        } catch (error) {
                if (typeof logError === "function") {
                        logError(error);
                }
                const notification = { type: "error", message: GIT_SUBMIT_ERROR_MESSAGE };
                deliverFeedback(notification, notifier, alertFn);
                return {
                        success: false,
                        error,
                        ...(typeof notifier === "function" ? { notification } : {}),
                };
        }
}
