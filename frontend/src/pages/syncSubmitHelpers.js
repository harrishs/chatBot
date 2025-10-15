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
        alertFn,
        resetForm,
        reload,
        logError,
}) {
        event?.preventDefault?.();

        if (!newJira?.credential_id) {
                alertFn?.(SYNC_MISSING_CREDENTIAL_MESSAGE);
                return { success: false, reason: "missing-credential" };
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
                alertFn?.(JIRA_SUBMIT_ERROR_MESSAGE);
                return { success: false, error };
        }
}

export async function handleConfluenceSubmit({
        event,
        newConfluence,
        chatBotId,
        apiClient,
        alertFn,
        resetForm,
        reload,
        logError,
}) {
        event?.preventDefault?.();

        if (!newConfluence?.credential_id) {
                alertFn?.(SYNC_MISSING_CREDENTIAL_MESSAGE);
                return { success: false, reason: "missing-credential" };
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
                alertFn?.(CONFLUENCE_SUBMIT_ERROR_MESSAGE);
                return { success: false, error };
        }
}
