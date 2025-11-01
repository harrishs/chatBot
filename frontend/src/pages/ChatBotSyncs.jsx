import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../api/axios";
import { useNotifications } from "../context/NotificationsContext.jsx";
import { useAuth } from "../context/AuthContext.jsx";
import { handleGitSubmit } from "./gitSubmitHelper";
import { handleJiraSubmit, handleConfluenceSubmit } from "./syncSubmitHelpers";

const SUMMARY_TYPE_METADATA = {
        jira: { label: "Jira" },
        confluence: { label: "Confluence" },
        git: { label: "Git" },
};

const ACTIVE_SYNC_STATUSES = new Set(["queued", "running"]);
const FAILED_SYNC_STATUS = "failed";

const SUMMARY_TYPE_ORDER = ["jira", "confluence", "git"];

const parseTimestamp = (value) => {
        if (!value) {
                return null;
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
                return null;
        }
        return date;
};

const normalizeTimestamp = (value) => {
        const date = parseTimestamp(value);
        if (!date) {
                return null;
        }
        return date.toISOString();
};

const getSyncLabel = (sync, type) => {
        if (type === "jira") {
                return sync.board_url || "Jira board";
        }
        if (type === "confluence") {
                return sync.space_url || "Confluence space";
        }
        if (type === "git") {
                const repo = sync.repo_full_name || "Git repository";
                const branch = sync.branch || "main";
                return `${repo} (${branch})`;
        }
        return SUMMARY_TYPE_METADATA[type]?.label || "Sync";
};

const computeSummaryFromSyncs = (jira = [], confluence = [], git = []) => {
        const breakdown = {
                jira: { label: SUMMARY_TYPE_METADATA.jira.label, total: 0, running: 0, failing: 0 },
                confluence: {
                        label: SUMMARY_TYPE_METADATA.confluence.label,
                        total: 0,
                        running: 0,
                        failing: 0,
                },
                git: { label: SUMMARY_TYPE_METADATA.git.label, total: 0, running: 0, failing: 0 },
        };

        const typedSyncs = [];

        const addSync = (sync, type) => {
                if (!sync) {
                        return;
                }
                const status = sync.sync_status || "idle";
                const entry = {
                        type,
                        id: sync.id,
                        label: getSyncLabel(sync, type),
                        status,
                        lastSyncTime: normalizeTimestamp(sync.last_sync_time),
                        nextSyncAt: normalizeTimestamp(sync.next_sync_at),
                        message: sync.sync_status_message || "",
                };
                typedSyncs.push(entry);

                const counts = breakdown[type];
                counts.total += 1;
                if (ACTIVE_SYNC_STATUSES.has(status)) {
                        counts.running += 1;
                }
                if (status === FAILED_SYNC_STATUS) {
                        counts.failing += 1;
                }
        };

        jira.forEach((sync) => addSync(sync, "jira"));
        confluence.forEach((sync) => addSync(sync, "confluence"));
        git.forEach((sync) => addSync(sync, "git"));

        const runningSyncs = typedSyncs.filter((sync) => ACTIVE_SYNC_STATUSES.has(sync.status)).length;
        const failingSyncs = typedSyncs.filter((sync) => sync.status === FAILED_SYNC_STATUS).length;

        let latestRun = null;
        let nextScheduled = null;
        let lastFailure = null;

        typedSyncs.forEach((sync) => {
                const lastSyncDate = parseTimestamp(sync.lastSyncTime);
                if (lastSyncDate) {
                        if (!latestRun || lastSyncDate > latestRun.rawDate) {
                                latestRun = {
                                        rawDate: lastSyncDate,
                                        detail: {
                                                type: sync.type,
                                                id: sync.id,
                                                label: sync.label,
                                                timestamp: lastSyncDate.toISOString(),
                                        },
                                };
                        }
                }

                const nextSyncDate = parseTimestamp(sync.nextSyncAt);
                if (nextSyncDate) {
                        if (!nextScheduled || nextSyncDate < nextScheduled.rawDate) {
                                nextScheduled = {
                                        rawDate: nextSyncDate,
                                        detail: {
                                                type: sync.type,
                                                id: sync.id,
                                                label: sync.label,
                                                timestamp: nextSyncDate.toISOString(),
                                        },
                                };
                        }
                }

                if (sync.status === FAILED_SYNC_STATUS) {
                        const failureDate = lastSyncDate || parseTimestamp(sync.nextSyncAt);
                        if (!lastFailure) {
                                lastFailure = {
                                        rawDate: failureDate,
                                        detail: {
                                                type: sync.type,
                                                id: sync.id,
                                                label: sync.label,
                                                message: sync.message || "",
                                                timestamp: failureDate ? failureDate.toISOString() : null,
                                        },
                                };
                        } else if (failureDate && lastFailure.rawDate) {
                                if (failureDate > lastFailure.rawDate) {
                                        lastFailure = {
                                                rawDate: failureDate,
                                                detail: {
                                                        type: sync.type,
                                                        id: sync.id,
                                                        label: sync.label,
                                                        message: sync.message || "",
                                                        timestamp: failureDate.toISOString(),
                                                },
                                        };
                                }
                        } else if (!lastFailure.rawDate && failureDate) {
                                lastFailure = {
                                        rawDate: failureDate,
                                        detail: {
                                                type: sync.type,
                                                id: sync.id,
                                                label: sync.label,
                                                message: sync.message || "",
                                                timestamp: failureDate.toISOString(),
                                        },
                                };
                        }
                }
        });

        return {
                totalSyncs: typedSyncs.length,
                runningSyncs,
                failingSyncs,
                latestRun: latestRun ? latestRun.detail : null,
                nextScheduled: nextScheduled ? nextScheduled.detail : null,
                lastFailure: lastFailure ? lastFailure.detail : null,
                breakdown,
        };
};

const adaptSummaryResponse = (data) => {
        if (!data || typeof data !== "object") {
                return null;
        }

        const mapDetail = (detail, includeMessage = false) => {
                if (!detail || typeof detail !== "object") {
                        return null;
                }
                const type = detail.type;
                if (!type) {
                        return null;
                }
                return {
                        type,
                        id: detail.id ?? null,
                        label:
                                detail.label ??
                                SUMMARY_TYPE_METADATA[type]?.label ??
                                SUMMARY_TYPE_METADATA.jira.label,
                        timestamp: detail.timestamp ?? null,
                        ...(includeMessage ? { message: detail.message ?? "" } : {}),
                };
        };

        const sourceBreakdown = data.breakdown || {};
        const breakdown = {};

        SUMMARY_TYPE_ORDER.forEach((type) => {
                const counts = sourceBreakdown[type] || {};
                breakdown[type] = {
                        label: SUMMARY_TYPE_METADATA[type].label,
                        total: counts.total ?? 0,
                        running: counts.running ?? 0,
                        failing: counts.failing ?? 0,
                };
        });

        return {
                totalSyncs: data.total_syncs ?? 0,
                runningSyncs: data.running_syncs ?? 0,
                failingSyncs: data.failing_syncs ?? 0,
                latestRun: mapDetail(data.latest_run),
                nextScheduled: mapDetail(data.next_scheduled),
                lastFailure: mapDetail(data.last_failure, true),
                breakdown,
        };
};

const mergeSummary = (localSummary, serverSummary) => {
        if (!serverSummary) {
                return localSummary;
        }

        const mergedBreakdown = {};
        SUMMARY_TYPE_ORDER.forEach((type) => {
                mergedBreakdown[type] = {
                        label:
                                serverSummary.breakdown?.[type]?.label ||
                                localSummary.breakdown?.[type]?.label ||
                                SUMMARY_TYPE_METADATA[type].label,
                        total:
                                serverSummary.breakdown?.[type]?.total ??
                                localSummary.breakdown?.[type]?.total ??
                                0,
                        running:
                                serverSummary.breakdown?.[type]?.running ??
                                localSummary.breakdown?.[type]?.running ??
                                0,
                        failing:
                                serverSummary.breakdown?.[type]?.failing ??
                                localSummary.breakdown?.[type]?.failing ??
                                0,
                };
        });

        return {
                totalSyncs: serverSummary.totalSyncs ?? localSummary.totalSyncs,
                runningSyncs: serverSummary.runningSyncs ?? localSummary.runningSyncs,
                failingSyncs: serverSummary.failingSyncs ?? localSummary.failingSyncs,
                latestRun: serverSummary.latestRun ?? localSummary.latestRun,
                nextScheduled: serverSummary.nextScheduled ?? localSummary.nextScheduled,
                lastFailure: serverSummary.lastFailure ?? localSummary.lastFailure,
                breakdown: mergedBreakdown,
        };
};

const formatSummaryTimestamp = (value) => {
        if (!value) {
                return null;
        }
        const date = parseTimestamp(value);
        if (!date) {
                return null;
        }
        return (
                new Intl.DateTimeFormat("en-US", {
                        dateStyle: "medium",
                        timeStyle: "short",
                        timeZone: "UTC",
                }).format(date) + " UTC"
        );
};

function ChatBotSyncs({ initialData = null }) {
        const { chatBotId } = useParams();
        const { notify } = useNotifications();
        const { user } = useAuth();

        const initialJira = initialData?.jiraSyncs ?? [];
        const initialConfluence = initialData?.confluenceSyncs ?? [];
        const initialGit = initialData?.gitSyncs ?? [];

        const [jiraSyncs, setJiraSyncs] = useState(initialJira);
        const [confluenceSyncs, setConfluenceSyncs] = useState(initialConfluence);
        const [credentials, setCredentials] = useState([]);
        const [gitSyncs, setGitSyncs] = useState(initialGit);
        const [gitCredentials, setGitCredentials] = useState([]);

        const [jiraFormMessage, setJiraFormMessage] = useState(null);
        const [confluenceFormMessage, setConfluenceFormMessage] = useState(null);
        const [gitFormMessage, setGitFormMessage] = useState(null);

	const [newJira, setNewJira] = useState({
		board_url: "",
		credential_id: "",
		sync_interval: "manual",
	});
	const [newConfluence, setNewConfluence] = useState({
		space_url: "",
		credential_id: "",
		sync_interval: "manual",
	});
	const [newGit, setNewGit] = useState({
		repo_full_name: "",
		branch: "main",
		credential_id: "",
		sync_interval: "manual",
	});

	const [editingJira, setEditingJira] = useState(null);
	const [editingConfluence, setEditingConfluence] = useState(null);
	const [editingJiraData, setEditingJiraData] = useState({
		board_url: "",
		credential_id: "",
		sync_interval: "manual",
	});
	const [editingConfluenceData, setEditingConfluenceData] = useState({
		space_url: "",
		credential_id: "",
		sync_interval: "manual",
	});
	const [editingGit, setEditingGit] = useState(null);
	const [editingGitData, setEditingGitData] = useState({
		repo_full_name: "",
		branch: "main",
		credential_id: "",
		sync_interval: "manual",
	});

        const [jobDetails, setJobDetails] = useState({});
        const initialSummary = initialData?.summary
                ? mergeSummary(
                          computeSummaryFromSyncs(initialJira, initialConfluence, initialGit),
                          initialData.summary,
                  )
                : computeSummaryFromSyncs(initialJira, initialConfluence, initialGit);
        const [syncSummary, setSyncSummary] = useState(initialSummary);
        const pollTimeouts = useRef({});
        const activePolls = useRef({});
        const serverSummaryRef = useRef(initialData?.summary ?? null);
        const canManage = user?.is_staff || user?.role === "admin";

	const makeJobKey = (type, id) => `${type}-${id}`;

	const updateSync = useCallback((type, id, updates) => {
		const setters = {
			jira: setJiraSyncs,
			confluence: setConfluenceSyncs,
			git: setGitSyncs,
		};

		const setter = setters[type];
		if (!setter) {
			return;
		}

		setter((prev) =>
			prev.map((sync) =>
				sync.id === id
					? {
							...sync,
							...updates,
					  }
					: sync
			)
		);
	}, []);

        const loadData = useCallback(async () => {
                try {
                        const [jiraRes, confRes, credRes, gitRes, gitCredRes] = await Promise.all(
                                [
                                        api.get(`/chatBots/${chatBotId}/jiraSyncs/`),
                                        api.get(`/chatBots/${chatBotId}/confluenceSyncs/`),
                                        api.get("/credentials/"),
                                        api.get(`/chatBots/${chatBotId}/gitRepoSyncs/`),
                                        api.get("/gitCredentials/"),
                                ]
                        );

                        const jiraData = jiraRes.data || [];
                        const confluenceData = confRes.data || [];
                        const gitData = gitRes.data || [];

                        setJiraSyncs(jiraData);
                        setConfluenceSyncs(confluenceData);
                        setCredentials(credRes.data || []);
                        setGitSyncs(gitData);
                        setGitCredentials(gitCredRes.data || []);

                        const localSummary = computeSummaryFromSyncs(
                                jiraData,
                                confluenceData,
                                gitData,
                        );
                        let mergedSummary = localSummary;

                        try {
                                const { data } = await api.get(
                                        `/chatBots/${chatBotId}/sync-summary/`,
                                );
                                const adapted = adaptSummaryResponse(data);
                                if (adapted) {
                                        serverSummaryRef.current = adapted;
                                        mergedSummary = mergeSummary(localSummary, adapted);
                                } else {
                                        serverSummaryRef.current = null;
                                }
                        } catch (summaryError) {
                                if (summaryError?.response?.status !== 404) {
                                        console.warn("Unable to load sync summary", summaryError);
                                }
                                serverSummaryRef.current = null;
                                mergedSummary = localSummary;
                        }

                        setSyncSummary(mergedSummary);
                } catch (err) {
                        console.error("Error loading syncs", err);
                        const fallbackSummary = computeSummaryFromSyncs();
                        serverSummaryRef.current = null;
                        setSyncSummary(fallbackSummary);
                }
        }, [chatBotId]);

	const stopPolling = useCallback((key) => {
		if (pollTimeouts.current[key]) {
			clearTimeout(pollTimeouts.current[key]);
			delete pollTimeouts.current[key];
		}
		delete activePolls.current[key];
		setJobDetails((prev) => {
			if (!prev[key]) {
				return prev;
			}
			return {
				...prev,
				[key]: {
					...prev[key],
					isPolling: false,
				},
			};
		});
	}, []);

	const pollStatus = useCallback(
		async (type, id, jobId) => {
			const key = makeJobKey(type, id);
			const resource =
				type === "jira"
					? "jiraSyncs"
					: type === "confluence"
					? "confluenceSyncs"
					: "gitRepoSyncs";

			const poll = async () => {
				try {
					const { data } = await api.get(
						`/chatBots/${chatBotId}/${resource}/${id}/status/`
					);

					updateSync(type, id, {
						sync_status: data.status,
						sync_status_message: data.message,
						current_job_id: data.job_id,
						job_status: data.job_status,
						job_message: data.job_message,
					});

					setJobDetails((prev) => ({
						...prev,
						[key]: {
							...(prev[key] || {}),
							jobId: data.job_id,
							jobStatus: data.job_status || data.status,
							jobMessage: data.job_message || data.message,
							isPolling: true,
						},
					}));

					if (data.job_id && jobId && data.job_id !== jobId) {
						stopPolling(key);
						return;
					}

					const terminalStatuses = ["succeeded", "failed"];
                                        if (
                                                terminalStatuses.includes(data.job_status) ||
                                                terminalStatuses.includes(data.status)
                                        ) {
                                                stopPolling(key);
                                                if (data.job_status === "failed" || data.status === "failed") {
                                                        notify({
                                                                type: "error",
                                                                message:
                                                                        data.job_message ||
                                                                        data.message ||
                                                                        "Sync failed.",
                                                        });
                                                }
                                                await loadData();
                                                return;
                                        }
				} catch (error) {
					console.error("Error polling sync status", error);
					stopPolling(key);
					return;
				}

				pollTimeouts.current[key] = setTimeout(poll, 2000);
			};

			stopPolling(key);
			activePolls.current[key] = true;
			setJobDetails((prev) => ({
				...prev,
				[key]: {
					...(prev[key] || {}),
					jobId,
					jobStatus: "queued",
					isPolling: true,
				},
			}));
			await poll();
		},
                [chatBotId, loadData, notify, stopPolling, updateSync]
        );

        useEffect(() => {
                loadData();
        }, [loadData]);

        useEffect(() => {
                const localSummary = computeSummaryFromSyncs(
                        jiraSyncs,
                        confluenceSyncs,
                        gitSyncs,
                );
                const merged = mergeSummary(localSummary, serverSummaryRef.current);
                setSyncSummary(merged);
        }, [jiraSyncs, confluenceSyncs, gitSyncs]);

        useEffect(
                () => () => {
                        Object.values(pollTimeouts.current).forEach((timeoutId) => {
                                clearTimeout(timeoutId);
                        });
			pollTimeouts.current = {};
			activePolls.current = {};
		},
		[]
	);

	useEffect(() => {
		jiraSyncs.forEach((sync) => {
			if (
				sync.current_job_id &&
				["queued", "running"].includes(sync.sync_status)
			) {
				const key = makeJobKey("jira", sync.id);
				if (!activePolls.current[key]) {
					pollStatus("jira", sync.id, sync.current_job_id);
				}
			}
		});
	}, [jiraSyncs, pollStatus]);

	useEffect(() => {
		confluenceSyncs.forEach((sync) => {
			if (
				sync.current_job_id &&
				["queued", "running"].includes(sync.sync_status)
			) {
				const key = makeJobKey("confluence", sync.id);
				if (!activePolls.current[key]) {
					pollStatus("confluence", sync.id, sync.current_job_id);
				}
			}
		});
	}, [confluenceSyncs, pollStatus]);

	useEffect(() => {
		gitSyncs.forEach((sync) => {
			if (
				sync.current_job_id &&
				["queued", "running"].includes(sync.sync_status)
			) {
				const key = makeJobKey("git", sync.id);
				if (!activePolls.current[key]) {
					pollStatus("git", sync.id, sync.current_job_id);
				}
			}
		});
	}, [gitSyncs, pollStatus]);

        const triggerSyncNow = useCallback(
                async (type, id) => {
                        if (!canManage) {
                                return;
                        }
                        try {
                                const resource =
                                        type === "jira"
						? "jiraSyncs"
						: type === "confluence"
						? "confluenceSyncs"
						: "gitRepoSyncs";
				const endpoint = `/chatBots/${chatBotId}/${resource}/${id}/sync_now/`;
				const { data } = await api.post(endpoint);
				updateSync(type, id, {
					sync_status: data.status,
					sync_status_message: data.message,
					current_job_id: data.job_id,
				});
				const key = makeJobKey(type, id);
				setJobDetails((prev) => ({
					...prev,
					[key]: {
						jobId: data.job_id,
						jobStatus: data.status || "queued",
						jobMessage: data.message,
						isPolling: true,
					},
				}));
				await pollStatus(type, id, data.job_id);
                        } catch (error) {
                                console.error("Error triggering sync", error);
                                notify({
                                        type: "error",
                                        message:
                                                "Failed to queue sync job. Please check the configuration and try again.",
                                });
                        }
                },
                [canManage, chatBotId, notify, pollStatus, updateSync]
        );

        const submitJira = async (e) => {
                if (!canManage) {
                        e?.preventDefault?.();
                        return null;
                }
                const result = await handleJiraSubmit({
                        event: e,
                        newJira,
                        chatBotId,
                        apiClient: api,
                        notifier: notify,
                        resetForm: () =>
                                setNewJira({
                                        board_url: "",
                                        credential_id: "",
                                        sync_interval: "manual",
                                }),
                        reload: loadData,
                        logError: (err) => console.error("Error submitting Jira sync", err),
                });
                if (result?.reason === "missing-credential" && result?.notification) {
                        setJiraFormMessage(result.notification);
                } else {
                        setJiraFormMessage(null);
                }
        };

        const submitConfluence = async (e) => {
                if (!canManage) {
                        e?.preventDefault?.();
                        return null;
                }
                const result = await handleConfluenceSubmit({
                        event: e,
                        newConfluence,
                        chatBotId,
                        apiClient: api,
                        notifier: notify,
                        resetForm: () =>
                                setNewConfluence({
                                        space_url: "",
                                        credential_id: "",
                                        sync_interval: "manual",
                                }),
                        reload: loadData,
                        logError: (err) => console.error("Error submitting Confluence sync", err),
                });
                if (result?.reason === "missing-credential" && result?.notification) {
                        setConfluenceFormMessage(result.notification);
                } else {
                        setConfluenceFormMessage(null);
                }
        };

        const submitGit = async (e) => {
                if (!canManage) {
                        e?.preventDefault?.();
                        return null;
                }
                const result = await handleGitSubmit({
                        event: e,
                        newGit,
                        chatBotId,
                        apiClient: api,
                        notifier: notify,
                        resetForm: () =>
                                setNewGit({
                                        repo_full_name: "",
                                        branch: "main",
                                        credential_id: "",
                                        sync_interval: "manual",
                                }),
                        reload: loadData,
                        logError: (error) => console.error("Error submitting Git sync", error),
                });
                if (result?.reason === "missing-credential" && result?.notification) {
                        setGitFormMessage(result.notification);
                } else {
                        setGitFormMessage(null);
                }
        };

        const deleteJira = async (id) => {
                if (!canManage) {
                        return;
                }
                await api.delete(`/chatBots/${chatBotId}/jiraSyncs/${id}/`);
                setEditingJira(null);
                setEditingJiraData({
			board_url: "",
			credential_id: "",
			sync_interval: "manual",
		});
		loadData();
	};

        const deleteConfluence = async (id) => {
                if (!canManage) {
                        return;
                }
                await api.delete(`/chatBots/${chatBotId}/confluenceSyncs/${id}/`);
                setEditingConfluence(null);
                setEditingConfluenceData({
			space_url: "",
			credential_id: "",
			sync_interval: "manual",
		});
		loadData();
	};

        const deleteGit = async (id) => {
                if (!canManage) {
                        return;
                }
                await api.delete(`/chatBots/${chatBotId}/gitRepoSyncs/${id}/`);
                setEditingGit(null);
                setEditingGitData({
			repo_full_name: "",
			branch: "",
			credential_id: "",
			sync_interval: "manual",
		});
		loadData();
	};

        const editJira = async (e) => {
                e.preventDefault();
                if (!canManage) {
                        return;
                }
                try {
                        await api.patch(
                                `/chatBots/${chatBotId}/jiraSyncs/${editingJira}/`,
				editingJiraData
			);
			setEditingJira(null);
			setEditingJiraData({
				board_url: "",
				credential_id: "",
				sync_interval: "manual",
			});
			loadData();
		} catch (err) {
			console.error("Error editing Jira sync", err);
		}
	};

        const editConfluence = async (e) => {
                e.preventDefault();
                if (!canManage) {
                        return;
                }
                try {
                        await api.patch(
                                `/chatBots/${chatBotId}/confluenceSyncs/${editingConfluence}/`,
				editingConfluenceData
			);
			setEditingConfluence(null);
			setEditingConfluenceData({
				space_url: "",
				credential_id: "",
				sync_interval: "manual",
			});
			loadData();
		} catch (err) {
			console.error("Error editing Confluence sync", err);
		}
	};

        const editGit = async (e) => {
                e.preventDefault();
                if (!canManage) {
                        return;
                }
                try {
                        await api.patch(
                                `/chatBots/${chatBotId}/gitRepoSyncs/${editingGit}/`,
				editingGitData
			);
			setEditingGit(null);
			setEditingGitData({
				repo_full_name: "",
				branch: "",
				credential_id: "",
				sync_interval: "manual",
			});
			loadData();
		} catch (err) {
			console.error("Error editing Git sync", err);
		}
	};

	const syncJiraNow = async (id) => {
		await triggerSyncNow("jira", id);
	};

	const syncConfluenceNow = async (id) => {
		await triggerSyncNow("confluence", id);
	};

        const syncGitNow = async (id) => {
                await triggerSyncNow("git", id);
        };

        const typeLabel = (type) => SUMMARY_TYPE_METADATA[type]?.label || "Sync";
        const currentSummary = syncSummary || computeSummaryFromSyncs(jiraSyncs, confluenceSyncs, gitSyncs);
        const hasConfiguredSyncs = currentSummary.totalSyncs > 0;

        return (
                <div style={{ padding: "2rem" }}>
                        <h1>ChatBot Syncs</h1>
                        {!canManage && user && (
                                <p style={{ marginTop: "1rem", color: "#555" }}>
                                        You have read-only access. Contact an administrator to manage
                                        sync settings.
                                </p>
                        )}

                        <section
                                aria-label="Sync summary"
                                style={{
                                        margin: "1.5rem 0",
                                        padding: "1.5rem",
                                        borderRadius: "0.75rem",
                                        border: "1px solid #d1d5db",
                                        background: "#f9fafb",
                                }}
                        >
                                <h2 style={{ marginTop: 0 }}>Sync Summary</h2>
                                <div style={{ display: "grid", gap: "0.5rem", marginTop: "0.75rem" }}>
                                        <p style={{ margin: 0 }}>
                                                <strong>Total syncs:</strong> {currentSummary.totalSyncs}
                                        </p>
                                        <p style={{ margin: 0 }}>
                                                <strong>Failing syncs:</strong> {currentSummary.failingSyncs}
                                        </p>
                                        <p style={{ margin: 0 }}>
                                                <strong>Running or queued:</strong> {currentSummary.runningSyncs}
                                        </p>
                                        <p style={{ margin: 0 }}>
                                                <strong>Last completed run:</strong>{" "}
                                                {currentSummary.latestRun
                                                        ? `${typeLabel(currentSummary.latestRun.type)} (${currentSummary.latestRun.label}) — ${
                                                                  formatSummaryTimestamp(currentSummary.latestRun.timestamp) ||
                                                                  "Unknown time"
                                                          }`
                                                        : "No successful runs yet"}
                                        </p>
                                        <p style={{ margin: 0 }}>
                                                <strong>Next scheduled run:</strong>{" "}
                                                {currentSummary.nextScheduled
                                                        ? `${typeLabel(currentSummary.nextScheduled.type)} (${currentSummary.nextScheduled.label}) — ${
                                                                  formatSummaryTimestamp(
                                                                          currentSummary.nextScheduled.timestamp,
                                                                  ) || "Unknown time"
                                                          }`
                                                        : "Not scheduled"}
                                        </p>
                                </div>

                                {currentSummary.lastFailure && (
                                        <div
                                                style={{
                                                        marginTop: "1rem",
                                                        padding: "0.75rem",
                                                        borderRadius: "0.5rem",
                                                        background: "#fef2f2",
                                                        border: "1px solid #fca5a5",
                                                        color: "#7f1d1d",
                                                }}
                                        >
                                                <strong>Last failure:</strong>{" "}
                                                {typeLabel(currentSummary.lastFailure.type)} ({
                                                        currentSummary.lastFailure.label
                                                }) — {currentSummary.lastFailure.message || "Sync failed."}
                                                {currentSummary.lastFailure.timestamp && (
                                                        <span>
                                                                {" "}(
                                                                {formatSummaryTimestamp(
                                                                        currentSummary.lastFailure.timestamp,
                                                                )}
                                                                )
                                                        </span>
                                                )}
                                        </div>
                                )}

                                <div style={{ marginTop: "1rem" }}>
                                        <h3 style={{ margin: "0 0 0.5rem" }}>Breakdown</h3>
                                        <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
                                                {SUMMARY_TYPE_ORDER.map((type) => {
                                                        const counts = currentSummary.breakdown[type];
                                                        return (
                                                                <li key={type} style={{ marginBottom: "0.25rem" }}>
                                                                        <strong>{counts.label}:</strong> {counts.total} total, {counts.failing} failing, {counts.running} running
                                                                </li>
                                                        );
                                                })}
                                        </ul>
                                </div>

                                {!hasConfiguredSyncs && (
                                        <div
                                                style={{
                                                        marginTop: "1rem",
                                                        padding: "0.75rem",
                                                        borderRadius: "0.5rem",
                                                        background: "#eef2ff",
                                                        border: "1px solid #c7d2fe",
                                                        color: "#312e81",
                                                }}
                                        >
                                                <p style={{ margin: 0 }}>
                                                        No syncs configured yet. Start by connecting the sources your chat
                                                        bot relies on.
                                                </p>
                                                <p style={{ margin: "0.5rem 0 0" }}>
                                                        {canManage ? (
                                                                <>
                                                                        Set up <Link to="/credentials">credentials</Link> to
                                                                        start connecting your data sources.
                                                                </>
                                                        ) : (
                                                                <>
                                                                        Review <Link to="/credentials">credential setup</Link>{" "}
                                                                        or contact an administrator for assistance.
                                                                </>
                                                        )}
                                                </p>
                                        </div>
                                )}
                        </section>

                        <h2>Jira Syncs</h2>
                        {canManage && (
                                <form onSubmit={submitJira}>
                                        <input
                                                placeholder="Jira Board URL"
                                                value={newJira.board_url}
                                                onChange={(e) =>
                                                        setNewJira({ ...newJira, board_url: e.target.value })
                                                }
                                        />
                                        <select
                                                value={newJira.credential_id}
                                                onChange={(e) => {
                                                        const value = e.target.value;
                                                        setNewJira({
                                                                ...newJira,
                                                                credential_id: value ? parseInt(value, 10) : "",
                                                        });
                                                        if (jiraFormMessage) {
                                                                setJiraFormMessage(null);
                                                        }
                                                }}
                                        >
                                                <option value="">Select Credential</option>
                                                {credentials.map((cred) => (
                                                        <option key={cred.id} value={cred.id}>
                                                                {cred.name}
                                                        </option>
                                                ))}
                                        </select>
                                        {jiraFormMessage?.placement === "inline" && (
                                                <div
                                                        style={{
                                                                marginTop: "0.5rem",
                                                                padding: "0.5rem 0.75rem",
                                                                borderRadius: "0.375rem",
                                                                background: "#fdecea",
                                                                border: "1px solid #f28b82",
                                                                color: "#b71c1c",
                                                                fontSize: "0.85rem",
                                                        }}
                                                >
                                                        {jiraFormMessage.message}
                                                </div>
                                        )}
                                        <select
                                                value={newJira.sync_interval}
                                                onChange={(e) =>
                                                        setNewJira({ ...newJira, sync_interval: e.target.value })
                                                }
                                        >
                                                <option value="manual">Manual</option>
                                                <option value="daily">Daily</option>
                                                <option value="weekly">Weekly</option>
                                                <option value="monthly">Monthly</option>
                                        </select>
                                        <button type="submit">Add Jira Sync</button>
                                </form>
                        )}

                        {jiraSyncs.length === 0 ? (
                                <div
                                        style={{
                                                marginTop: "1rem",
                                                padding: "1rem",
                                                border: "1px dashed #d1d5db",
                                                borderRadius: "0.5rem",
                                        }}
                                >
                                        <p style={{ margin: 0 }}>No Jira syncs have been configured yet.</p>
                                        <p style={{ margin: "0.5rem 0 0" }}>
                                                {canManage ? (
                                                        <>
                                                                Visit <Link to="/credentials">Credentials</Link> to add an
                                                                integration key, then create your first Jira sync.
                                                        </>
                                                ) : (
                                                        <>
                                                                Ask an administrator to configure Jira syncs or review{" "}
                                                                <Link to="/credentials">credential setup</Link> for more
                                                                details.
                                                        </>
                                                )}
                                        </p>
                                </div>
                        ) : (
                                <ul>
                                        {jiraSyncs.map((sync) => (
                                                <li key={sync.id}>
                                                        {canManage && editingJira === sync.id ? (
                                                                <form onSubmit={editJira}>
                                                                        <input
                                                                                value={editingJiraData.board_url}
                                                                                onChange={(e) =>
                                                                                        setEditingJiraData({
                                                                                                ...editingJiraData,
                                                                                                board_url: e.target.value,
                                                                                        })
                                                                                }
                                                                        />
                                                                        <select
                                                                                value={editingJiraData.credential_id}
                                                                                onChange={(e) =>
                                                                                        setEditingJiraData({
                                                                                                ...editingJiraData,
                                                                                                credential_id: parseInt(
                                                                                                        e.target.value,
                                                                                                        10,
                                                                                                ),
                                                                                        })
                                                                                }
                                                                        >
                                                                                <option value="">Select Credential</option>
                                                                                {credentials.map((cred) => (
                                                                                        <option key={cred.id} value={cred.id}>
                                                                                                {cred.name}
                                                                                        </option>
                                                                                ))}
                                                                        </select>
                                                                        <select
                                                                                value={editingJiraData.sync_interval}
                                                                                onChange={(e) =>
                                                                                        setEditingJiraData({
                                                                                                ...editingJiraData,
                                                                                                sync_interval: e.target.value,
                                                                                        })
                                                                                }
                                                                        >
                                                                                <option value="manual">Manual</option>
                                                                                <option value="daily">Daily</option>
                                                                                <option value="weekly">Weekly</option>
                                                                                <option value="monthly">Monthly</option>
                                                                        </select>
                                                                        <button type="submit">Save</button>
                                                                        <button
                                                                                type="button"
                                                                                onClick={() => setEditingJira(null)}
                                                                        >
                                                                                Cancel
                                                                        </button>
                                                                </form>
                                                        ) : (
                                                                <>
                                                                        {sync.board_url} (Credential: {sync.credential?.name})
                                                                        {canManage && (
                                                                                <button
                                                                                        onClick={() => {
                                                                                                setEditingJira(sync.id);
                                                                                                setEditingJiraData({
                                                                                                        board_url:
                                                                                                                sync.board_url,
                                                                                                        credential_id:
                                                                                                                sync.credential?.id,
                                                                                                        sync_interval:
                                                                                                                sync.sync_interval,
                                                                                                });
                                                                                        }}
                                                                                >
                                                                                        Edit
                                                                                </button>
                                                                        )}
                                                                </>
                                                        )}
                                                        <div>
                                                                <strong>Status:</strong> {sync.sync_status || "idle"}
                                                                {jobDetails[makeJobKey("jira", sync.id)]?.isPolling && (
                                                                        <span style={{ marginLeft: "0.5rem" }}>
                                                                                Checking status...
                                                                        </span>
                                                                )}
                                                        </div>
                                                        {sync.sync_status_message && <div>{sync.sync_status_message}</div>}
                                                        {jobDetails[makeJobKey("jira", sync.id)]?.jobMessage && (
                                                                <div>
                                                                        <em>
                                                                                Job message:{" "}
                                                                                {jobDetails[makeJobKey("jira", sync.id)]?.jobMessage}
                                                                        </em>
                                                                </div>
                                                        )}
                                                        {canManage && (
                                                                <>
                                                                        <button onClick={() => deleteJira(sync.id)}>
                                                                                Delete
                                                                        </button>
                                                                        <button onClick={() => syncJiraNow(sync.id)}>
                                                                                Sync Now
                                                                        </button>
                                                                </>
                                                        )}
                                                </li>
                                        ))}
                                </ul>
                        )}

			<h2>Confluence Syncs</h2>
                        {canManage && (
                                <form onSubmit={submitConfluence}>
                                        <input
                                                placeholder="Confluence Space URL"
                                                value={newConfluence.space_url}
                                                onChange={(e) =>
                                                        setNewConfluence({
                                                                ...newConfluence,
                                                                space_url: e.target.value,
                                                        })
                                                }
                                        />
                                        <select
                                                value={newConfluence.credential_id}
                                                onChange={(e) => {
                                                        const value = e.target.value;
                                                        setNewConfluence({
                                                                ...newConfluence,
                                                                credential_id: value ? parseInt(value, 10) : "",
                                                        });
                                                        if (confluenceFormMessage) {
                                                                setConfluenceFormMessage(null);
                                                        }
                                                }}
                                        >
                                                <option value="">Select Credential</option>
                                                {credentials.map((cred) => (
                                                        <option key={cred.id} value={cred.id}>
                                                                {cred.name}
                                                        </option>
                                                ))}
                                        </select>
                                        {confluenceFormMessage?.placement === "inline" && (
                                                <div
                                                        style={{
                                                                marginTop: "0.5rem",
                                                                padding: "0.5rem 0.75rem",
                                                                borderRadius: "0.375rem",
                                                                background: "#fdecea",
                                                                border: "1px solid #f28b82",
                                                                color: "#b71c1c",
                                                                fontSize: "0.85rem",
                                                        }}
                                                >
                                                        {confluenceFormMessage.message}
                                                </div>
                                        )}
                                        <select
                                                value={newConfluence.sync_interval}
                                                onChange={(e) =>
                                                        setNewConfluence({
                                                                ...newConfluence,
                                                                sync_interval: e.target.value,
                                                        })
                                                }
                                        >
                                                <option value="manual">Manual</option>
                                                <option value="daily">Daily</option>
                                                <option value="weekly">Weekly</option>
                                                <option value="monthly">Monthly</option>
                                        </select>
                                        <button type="submit">Add Confluence Sync</button>
                                </form>
                        )}

                        {confluenceSyncs.length === 0 ? (
                                <div
                                        style={{
                                                marginTop: "1rem",
                                                padding: "1rem",
                                                border: "1px dashed #d1d5db",
                                                borderRadius: "0.5rem",
                                        }}
                                >
                                        <p style={{ margin: 0 }}>No Confluence syncs have been configured yet.</p>
                                        <p style={{ margin: "0.5rem 0 0" }}>
                                                {canManage ? (
                                                        <>
                                                                Connect your wiki by configuring <Link to="/credentials">credentials</Link>{" "}
                                                                and adding a Confluence sync.
                                                        </>
                                                ) : (
                                                        <>
                                                                Contact an administrator or review{" "}
                                                                <Link to="/credentials">credential setup</Link> for how to
                                                                enable Confluence syncs.
                                                        </>
                                                )}
                                        </p>
                                </div>
                        ) : (
                                <ul>
                                        {confluenceSyncs.map((sync) => (
                                                <li key={sync.id}>
                                                        {canManage && editingConfluence === sync.id ? (
                                                                <form onSubmit={editConfluence}>
                                                                        <input
                                                                                value={editingConfluenceData.space_url}
                                                                                onChange={(e) =>
                                                                                        setEditingConfluenceData({
                                                                                                ...editingConfluenceData,
                                                                                                space_url: e.target.value,
                                                                                        })
                                                                                }
                                                                        />
                                                                        <select
                                                                                value={editingConfluenceData.credential_id}
                                                                                onChange={(e) =>
                                                                                        setEditingConfluenceData({
                                                                                                ...editingConfluenceData,
                                                                                                credential_id: parseInt(
                                                                                                        e.target.value,
                                                                                                        10,
                                                                                                ),
                                                                                        })
                                                                                }
                                                                        >
                                                                                <option value="">Select Credential</option>
                                                                                {credentials.map((cred) => (
                                                                                        <option key={cred.id} value={cred.id}>
                                                                                                {cred.name}
                                                                                        </option>
                                                                                ))}
                                                                        </select>
                                                                        <select
                                                                                value={editingConfluenceData.sync_interval}
                                                                                onChange={(e) =>
                                                                                        setEditingConfluenceData({
                                                                                                ...editingConfluenceData,
                                                                                                sync_interval:
                                                                                                        e.target.value,
                                                                                        })
                                                                                }
                                                                        >
                                                                                <option value="manual">Manual</option>
                                                                                <option value="daily">Daily</option>
                                                                                <option value="weekly">Weekly</option>
                                                                                <option value="monthly">Monthly</option>
                                                                        </select>
                                                                        <button type="submit">Save</button>
                                                                        <button
                                                                                type="button"
                                                                                onClick={() => setEditingConfluence(null)}
                                                                        >
                                                                                Cancel
                                                                        </button>
                                                                </form>
                                                        ) : (
                                                                <>
                                                                        {sync.space_url} (Credential: {sync.credential?.name})
                                                                        {canManage && (
                                                                                <button
                                                                                        onClick={() => {
                                                                                                setEditingConfluence(sync.id);
                                                                                                setEditingConfluenceData({
                                                                                                        space_url:
                                                                                                                sync.space_url,
                                                                                                        credential_id:
                                                                                                                sync.credential?.id,
                                                                                                        sync_interval:
                                                                                                                sync.sync_interval,
                                                                                                });
                                                                                        }}
                                                                                >
                                                                                        Edit
                                                                                </button>
                                                                        )}
                                                                </>
                                                        )}
                                                        <div>
                                                                <strong>Status:</strong> {sync.sync_status || "idle"}
                                                                {jobDetails[makeJobKey("confluence", sync.id)]?.isPolling && (
                                                                        <span style={{ marginLeft: "0.5rem" }}>
                                                                                Checking status...
                                                                        </span>
                                                                )}
                                                        </div>
                                                        {sync.sync_status_message && <div>{sync.sync_status_message}</div>}
                                                        {jobDetails[makeJobKey("confluence", sync.id)]?.jobMessage && (
                                                                <div>
                                                                        <em>
                                                                                Job message:{" "}
                                                                                {jobDetails[makeJobKey("confluence", sync.id)]?.jobMessage}
                                                                        </em>
                                                                </div>
                                                        )}
                                                        {canManage && (
                                                                <>
                                                                        <button onClick={() => deleteConfluence(sync.id)}>
                                                                                Delete
                                                                        </button>
                                                                        <button onClick={() => syncConfluenceNow(sync.id)}>
                                                                                Sync Now
                                                                        </button>
                                                                </>
                                                        )}
                                                </li>
                                        ))}
                                </ul>
                        )}

			<h2>Git Repository Syncs</h2>
                        {canManage && (
                                <form onSubmit={submitGit}>
                                        <input
                                                placeholder="Repo Full Name (e.g., owner/repo)"
                                                value={newGit.repo_full_name}
                                                onChange={(e) =>
                                                        setNewGit({ ...newGit, repo_full_name: e.target.value })
                                                }
                                        />
                                        <input
                                                placeholder="Branch"
                                                value={newGit.branch}
                                                onChange={(e) => setNewGit({ ...newGit, branch: e.target.value })}
                                        />
                                        <select
                                                value={newGit.credential_id}
                                                onChange={(e) => {
                                                        const value = e.target.value;
                                                        setNewGit({
                                                                ...newGit,
                                                                credential_id: value ? parseInt(value, 10) : "",
                                                        });
                                                        if (gitFormMessage) {
                                                                setGitFormMessage(null);
                                                        }
                                                }}
                                        >
                                                <option value="">Select credential</option>
                                                {gitCredentials.map((c) => (
                                                        <option key={c.id} value={c.id}>
                                                                {c.name}
                                                        </option>
                                                ))}
                                        </select>
                                        {gitFormMessage?.placement === "inline" && (
                                                <div
                                                        style={{
                                                                marginTop: "0.5rem",
                                                                padding: "0.5rem 0.75rem",
                                                                borderRadius: "0.375rem",
                                                                background: "#fdecea",
                                                                border: "1px solid #f28b82",
                                                                color: "#b71c1c",
                                                                fontSize: "0.85rem",
                                                        }}
                                                >
                                                        {gitFormMessage.message}
                                                </div>
                                        )}
                                        <select
                                                value={newGit.sync_interval}
                                                onChange={(e) =>
                                                        setNewGit({ ...newGit, sync_interval: e.target.value })
                                                }
                                        >
                                                <option value="manual">Manual</option>
                                                <option value="daily">Daily</option>
                                                <option value="weekly">Weekly</option>
                                                <option value="monthly">Monthly</option>
                                        </select>
                                        <button type="submit">Add Git Sync</button>
                                </form>
                        )}
                        {gitSyncs.length === 0 ? (
                                <div
                                        style={{
                                                marginTop: "1rem",
                                                padding: "1rem",
                                                border: "1px dashed #d1d5db",
                                                borderRadius: "0.5rem",
                                        }}
                                >
                                        <p style={{ margin: 0 }}>No Git repository syncs have been configured yet.</p>
                                        <p style={{ margin: "0.5rem 0 0" }}>
                                                {canManage ? (
                                                        <>
                                                                Create a Git credential on the <Link to="/credentials">Credentials</Link>{" "}
                                                                page to start syncing repositories.
                                                        </>
                                                ) : (
                                                        <>
                                                                Ask an administrator to link repository credentials or review{" "}
                                                                <Link to="/credentials">credential setup</Link> to learn more.
                                                        </>
                                                )}
                                        </p>
                                </div>
                        ) : (
                                <ul>
                                        {gitSyncs.map((sync) => (
					<li key={sync.id}>
                                                {canManage && editingGit === sync.id ? (
							<form onSubmit={editGit}>
								<input
									value={editingGitData.repo_full_name}
									onChange={(e) =>
										setEditingGitData({
											...editingGitData,
											repo_full_name: e.target.value,
										})
									}
								/>
								<input
									value={editingGitData.branch}
									onChange={(e) =>
										setEditingGitData({
											...editingGitData,
											branch: e.target.value,
										})
									}
								/>
								<select
									value={editingGitData.credential_id}
									onChange={(e) =>
										setEditingGitData({
											...editingGitData,
											credential_id: parseInt(e.target.value, 10),
										})
									}
								>
									<option value="">Select Credential</option>
									{gitCredentials.map((cred) => (
										<option key={cred.id} value={cred.id}>
											{cred.name}
										</option>
									))}
								</select>
								<select
									value={editingGitData.sync_interval}
									onChange={(e) =>
										setEditingGitData({
											...editingGitData,
											sync_interval: e.target.value,
										})
									}
								>
									<option value="manual">Manual</option>
									<option value="daily">Daily</option>
									<option value="weekly">Weekly</option>
									<option value="monthly">Monthly</option>
								</select>
								<button type="submit">Save</button>
								<button type="button" onClick={() => setEditingGit(null)}>
									Cancel
								</button>
							</form>
						) : (
							<>
								{sync.repo_full_name} - {sync.branch} (Credential:{" "}
								{sync.credential?.name})
                                                                {canManage && (
                                                                        <button
                                                                                onClick={() => {
                                                                                        setEditingGit(sync.id);
                                                                                        setEditingGitData({
                                                                                                repo_full_name:
                                                                                                        sync.repo_full_name,
                                                                                                branch: sync.branch,
                                                                                                credential_id: parseInt(
                                                                                                        sync.credential?.id,
                                                                                                        10,
                                                                                                ),
                                                                                                sync_interval:
                                                                                                        sync.sync_interval,
                                                                                        });
                                                                                }}
                                                                        >
                                                                                Edit
                                                                        </button>
                                                                )}
							</>
						)}
						<div>
							<strong>Status:</strong> {sync.sync_status || "idle"}
							{jobDetails[makeJobKey("git", sync.id)]?.isPolling && (
								<span style={{ marginLeft: "0.5rem" }}>Checking status...</span>
							)}
						</div>
						{sync.sync_status_message && <div>{sync.sync_status_message}</div>}
						{jobDetails[makeJobKey("git", sync.id)]?.jobMessage && (
							<div>
								<em>
									Job message:{" "}
									{jobDetails[makeJobKey("git", sync.id)]?.jobMessage}
								</em>
							</div>
						)}
                                                {canManage && (
                                                        <>
                                                                <button onClick={() => deleteGit(sync.id)}>
                                                                        Delete
                                                                </button>
                                                                <button onClick={() => syncGitNow(sync.id)}>
                                                                        Sync Now
                                                                </button>
                                                        </>
                                                )}
					</li>
                                ))}
                                </ul>
                        )}
                </div>
        );
}

export default ChatBotSyncs;
