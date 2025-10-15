export const GIT_MISSING_CREDENTIAL_MESSAGE =
        "Please select a Git credential before adding the sync.";
export const GIT_SUBMIT_ERROR_MESSAGE =
        "Failed to create Git sync. Please check the configuration and try again.";

export async function handleGitSubmit({
        event,
        newGit,
        chatBotId,
        apiClient,
        alertFn,
        resetForm,
        reload,
        logError,
}) {
        event?.preventDefault?.();

        if (!newGit?.credential_id) {
                alertFn?.(GIT_MISSING_CREDENTIAL_MESSAGE);
                return { success: false, reason: "missing-credential" };
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
                alertFn?.(GIT_SUBMIT_ERROR_MESSAGE);
                return { success: false, error };
        }
}
