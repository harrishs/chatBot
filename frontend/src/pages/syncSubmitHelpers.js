export const SYNC_MISSING_CREDENTIAL_MESSAGE =
        "Please select a credential before adding the sync.";
export const JIRA_SUBMIT_ERROR_MESSAGE =
        "Failed to create Jira sync. Please check the configuration and try again.";
export const CONFLUENCE_SUBMIT_ERROR_MESSAGE =
        "Failed to create Confluence sync. Please check the configuration and try again.";

export async function handleJiraSubmit({
        event,
        newJira,
        chatBotId,
        apiClient,
        notifier,
        resetForm,
        reload,
        logError,
}) {
        event?.preventDefault?.();

        if (!newJira?.credential_id) {
                const notification = {
                        type: "error",
                        message: SYNC_MISSING_CREDENTIAL_MESSAGE,
                };
                notifier?.(notification);
                return { success: false, reason: "missing-credential", notification };
        }

        try {
                await apiClient.post(`/chatBots/${chatBotId}/jiraSyncs/`, newJira);
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
                const notification = { type: "error", message: JIRA_SUBMIT_ERROR_MESSAGE };
                notifier?.(notification);
                return { success: false, error, notification };
        }
}

export async function handleConfluenceSubmit({
        event,
        newConfluence,
        chatBotId,
        apiClient,
        notifier,
        resetForm,
        reload,
        logError,
}) {
        event?.preventDefault?.();

        if (!newConfluence?.credential_id) {
                const notification = {
                        type: "error",
                        message: SYNC_MISSING_CREDENTIAL_MESSAGE,
                };
                notifier?.(notification);
                return { success: false, reason: "missing-credential", notification };
        }

        try {
                await apiClient.post(
                        `/chatBots/${chatBotId}/confluenceSyncs/`,
                        newConfluence,
                );
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
                const notification = {
                        type: "error",
                        message: CONFLUENCE_SUBMIT_ERROR_MESSAGE,
                };
                notifier?.(notification);
                return { success: false, error, notification };
        }
}
