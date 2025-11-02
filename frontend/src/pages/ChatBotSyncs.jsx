import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import api from "../api/axios";
import { useAuth } from "../context/AuthContext.jsx";
import { handleGitSubmit } from "./gitSubmitHelper";
import { handleJiraSubmit, handleConfluenceSubmit } from "./syncSubmitHelpers";
import {
        Notifications,
        NOTIFICATION_TYPE_COLORS,
        useNotifications,
} from "../hooks/useNotifications";

const STATUS_LABELS = {
        idle: "Idle",
        queued: "Queued",
        running: "Running",
        succeeded: "Succeeded",
        failed: "Failed",
};

const SYNC_TYPE_CONFIG = {
        jira: {
                label: "Jira",
                emptyLabel: "Jira",
                getName: (sync) => sync.board_url || `Jira sync #${sync.id}`,
        },
        confluence: {
                label: "Confluence",
                emptyLabel: "Confluence",
                getName: (sync) => sync.space_url || `Confluence sync #${sync.id}`,
        },
        git: {
                label: "Git Repository",
                emptyLabel: "Git repository",
                getName: (sync) => {
                        const repo = sync.repo_full_name || `Repo sync #${sync.id}`;
                        return sync.branch ? `${repo}@${sync.branch}` : repo;
                },
        },
};

const SYNC_TYPE_KEYS = ["jira", "confluence", "git"];

const parseDateValue = (value) => {
        if (!value) {
                return null;
        }
        if (value instanceof Date && !Number.isNaN(value.getTime())) {
                return value;
        }
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
};

const formatDateUtc = (date) => {
        if (!date) {
                return "";
        }
        const parsed = parseDateValue(date);
        if (!parsed) {
                return "";
        }
        const pad = (num) => String(num).padStart(2, "0");
        const year = parsed.getUTCFullYear();
        const month = pad(parsed.getUTCMonth() + 1);
        const day = pad(parsed.getUTCDate());
        const hours = pad(parsed.getUTCHours());
        const minutes = pad(parsed.getUTCMinutes());
        return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
};

const summaryPanelStyle = {
        border: "1px solid #ddd",
        borderRadius: "8px",
        padding: "1rem",
        marginTop: "1.5rem",
        marginBottom: "2rem",
        backgroundColor: "#fafafa",
};

const summaryListStyle = {
        margin: "0.5rem 0",
        paddingLeft: "1.25rem",
};

const emptyStateStyle = {
        margin: "0.75rem 0",
        color: "#555",
};

const inlineMessageBaseStyle = {
        margin: "0.5rem 0 0",
        fontSize: "0.9rem",
        lineHeight: 1.4,
};

function ChatBotSyncs({ initialSyncData = null }) {
        const { chatBotId } = useParams();

        const [jiraSyncs, setJiraSyncs] = useState(() => initialSyncData?.jiraSyncs ?? []);
        const [confluenceSyncs, setConfluenceSyncs] = useState(
                () => initialSyncData?.confluenceSyncs ?? []
        );
        const [credentials, setCredentials] = useState(() => initialSyncData?.credentials ?? []);
        const [gitSyncs, setGitSyncs] = useState(() => initialSyncData?.gitSyncs ?? []);
        const [gitCredentials, setGitCredentials] = useState(
                () => initialSyncData?.gitCredentials ?? []
        );
        const [syncSummary, setSyncSummary] = useState(() => initialSyncData?.summary ?? null);

        const [formMessages, setFormMessages] = useState({
                jira: null,
                confluence: null,
                git: null,
        });

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
        const pollTimeouts = useRef({});
        const activePolls = useRef({});
        const { user } = useAuth();
        const canManage = user?.is_staff || user?.role === "admin";

        const { notifications, notify, dismiss } = useNotifications();

        useEffect(() => {
                if (!initialSyncData) {
                        return;
                }
                setJiraSyncs(initialSyncData.jiraSyncs ?? []);
                setConfluenceSyncs(initialSyncData.confluenceSyncs ?? []);
                setGitSyncs(initialSyncData.gitSyncs ?? []);
                setCredentials(initialSyncData.credentials ?? []);
                setGitCredentials(initialSyncData.gitCredentials ?? []);
                setSyncSummary(initialSyncData.summary ?? null);
        }, [initialSyncData]);

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
                        setJiraSyncs(jiraRes.data);
                        setConfluenceSyncs(confRes.data);
                        setCredentials(credRes.data);
                        setGitSyncs(gitRes.data);
                        setGitCredentials(gitCredRes.data);
                        setSyncSummary(null);
                        try {
                                const summaryRes = await api.get(
                                        `/chatBots/${chatBotId}/sync-summary/`
                                );
                                setSyncSummary(summaryRes.data);
                        } catch (summaryError) {
                                console.warn("Error loading sync summary", summaryError);
                                setSyncSummary(null);
                        }
                } catch (err) {
                        console.error("Error loading syncs", err);
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
                if (initialSyncData) {
                        return;
                }
                loadData();
        }, [initialSyncData, loadData]);

        useEffect(() => {
                if (!canManage) {
                        setEditingJira(null);
                        setEditingConfluence(null);
                        setEditingGit(null);
                        setEditingJiraData({
                                board_url: "",
                                credential_id: "",
                                sync_interval: "manual",
                        });
                        setEditingConfluenceData({
                                space_url: "",
                                credential_id: "",
                                sync_interval: "manual",
                        });
                        setEditingGitData({
                                repo_full_name: "",
                                branch: "main",
                                credential_id: "",
                                sync_interval: "manual",
                        });
                }
        }, [canManage]);

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
                        if (!canManage) return;
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
                                const defaultQueuedMessage = SYNC_TYPE_CONFIG[type]?.label
                                        ? `Sync job queued for ${SYNC_TYPE_CONFIG[type].label}.`
                                        : "Sync job queued.";
                                notify({
                                        type: "success",
                                        message: data?.message || defaultQueuedMessage,
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
                if (!canManage) return;
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
                setFormMessages((prev) => ({
                        ...prev,
                        jira:
                                result?.reason === "missing-credential"
                                        ? result.notification
                                        : result?.success
                                        ? null
                                        : prev.jira,
                }));
        };

        const submitConfluence = async (e) => {
                if (!canManage) return;
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
                setFormMessages((prev) => ({
                        ...prev,
                        confluence:
                                result?.reason === "missing-credential"
                                        ? result.notification
                                        : result?.success
                                        ? null
                                        : prev.confluence,
                }));
        };

        const submitGit = async (e) => {
                if (!canManage) return;
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
                setFormMessages((prev) => ({
                        ...prev,
                        git:
                                result?.reason === "missing-credential"
                                        ? result.notification
                                        : result?.success
                                        ? null
                                        : prev.git,
                }));
        };

        const deleteJira = async (id) => {
                if (!canManage) return;
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
                if (!canManage) return;
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
                if (!canManage) return;
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
                if (!canManage) return;
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
                if (!canManage) return;
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
                if (!canManage) return;
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
                if (!canManage) return;
                await triggerSyncNow("jira", id);
        };

        const syncConfluenceNow = async (id) => {
                if (!canManage) return;
                await triggerSyncNow("confluence", id);
        };

        const syncGitNow = async (id) => {
                if (!canManage) return;
                await triggerSyncNow("git", id);
        };

        const aggregatedSummary = useMemo(() => {
                const summary = {
                        total: 0,
                        failing: 0,
                        running: 0,
                        latestRun: null,
                        nextScheduled: null,
                        types: {},
                        failingSyncs: [],
                        statuses: {},
                };

                const collections = {
                        jira: jiraSyncs,
                        confluence: confluenceSyncs,
                        git: gitSyncs,
                };

                SYNC_TYPE_KEYS.forEach((key) => {
                        const data = collections[key] || [];
                        const typeMeta = SYNC_TYPE_CONFIG[key] || {
                                label: key,
                                emptyLabel: key,
                                getName: (sync) => sync.id ? `Sync #${sync.id}` : key,
                        };

                        const typeInfo = {
                                label: typeMeta.label,
                                total: data.length,
                                failing: 0,
                                running: 0,
                                latestRun: null,
                                nextScheduled: null,
                                statuses: {},
                        };

                        summary.total += data.length;

                        data.forEach((sync) => {
                                const status = (sync.sync_status || "idle").toLowerCase();
                                typeInfo.statuses[status] = (typeInfo.statuses[status] || 0) + 1;
                                summary.statuses[status] = (summary.statuses[status] || 0) + 1;

                                const name = typeMeta.getName(sync);

                                if (status === "failed") {
                                        typeInfo.failing += 1;
                                        summary.failing += 1;
                                        summary.failingSyncs.push({
                                                type: typeMeta.label,
                                                name,
                                                id: sync.id,
                                        });
                                }

                                if (status === "running" || status === "queued") {
                                        typeInfo.running += 1;
                                        summary.running += 1;
                                }

                                const lastSyncTime = parseDateValue(sync.last_sync_time);
                                if (lastSyncTime) {
                                        if (!typeInfo.latestRun || lastSyncTime > typeInfo.latestRun.date) {
                                                typeInfo.latestRun = {
                                                        date: lastSyncTime,
                                                        id: sync.id,
                                                        name,
                                                        status,
                                                        type: typeMeta.label,
                                                };
                                        }
                                        if (!summary.latestRun || lastSyncTime > summary.latestRun.date) {
                                                summary.latestRun = {
                                                        date: lastSyncTime,
                                                        id: sync.id,
                                                        name,
                                                        status,
                                                        type: typeMeta.label,
                                                };
                                        }
                                }

                                const nextSyncTime = parseDateValue(sync.next_sync_at);
                                if (nextSyncTime) {
                                        if (!typeInfo.nextScheduled || nextSyncTime < typeInfo.nextScheduled.date) {
                                                typeInfo.nextScheduled = {
                                                        date: nextSyncTime,
                                                        id: sync.id,
                                                        name,
                                                        type: typeMeta.label,
                                                };
                                        }
                                        if (!summary.nextScheduled || nextSyncTime < summary.nextScheduled.date) {
                                                summary.nextScheduled = {
                                                        date: nextSyncTime,
                                                        id: sync.id,
                                                        name,
                                                        type: typeMeta.label,
                                                };
                                        }
                                }
                        });

                        summary.types[key] = typeInfo;
                });

                return summary;
        }, [jiraSyncs, confluenceSyncs, gitSyncs]);

        const statusBreakdown = useMemo(() => {
                if (syncSummary?.overall?.statuses) {
                        return syncSummary.overall.statuses;
                }
                return aggregatedSummary.statuses;
        }, [aggregatedSummary, syncSummary]);

        const latestRunInfo = aggregatedSummary.latestRun
                ? aggregatedSummary.latestRun
                : syncSummary?.overall?.latest_sync?.occurred_at
                ? {
                          date: parseDateValue(syncSummary.overall.latest_sync.occurred_at),
                          type:
                                  syncSummary.overall.latest_sync.type_label ||
                                  SYNC_TYPE_CONFIG[syncSummary.overall.latest_sync.type]?.label ||
                                  syncSummary.overall.latest_sync.type,
                          id: syncSummary.overall.latest_sync.sync_id,
                          name: syncSummary.overall.latest_sync.name,
                  }
                : null;

        const nextScheduledInfo = aggregatedSummary.nextScheduled
                ? aggregatedSummary.nextScheduled
                : syncSummary?.overall?.next_scheduled?.scheduled_for
                ? {
                          date: parseDateValue(syncSummary.overall.next_scheduled.scheduled_for),
                          type:
                                  syncSummary.overall.next_scheduled.type_label ||
                                  SYNC_TYPE_CONFIG[syncSummary.overall.next_scheduled.type]?.label ||
                                  syncSummary.overall.next_scheduled.type,
                          id: syncSummary.overall.next_scheduled.sync_id,
                          name: syncSummary.overall.next_scheduled.name,
                  }
                : null;

        const typeSummariesInOrder = useMemo(
                () =>
                        SYNC_TYPE_KEYS.map((key) => {
                                const typeInfo = aggregatedSummary.types[key];
                                if (typeInfo) {
                                        return { key, ...typeInfo };
                                }
                                const meta = SYNC_TYPE_CONFIG[key];
                                return {
                                        key,
                                        label: meta?.label || key,
                                        total: 0,
                                        failing: 0,
                                        running: 0,
                                        latestRun: null,
                                        nextScheduled: null,
                                        statuses: {},
                                };
                        }),
                [aggregatedSummary]
        );

        const healthyMessage = aggregatedSummary.failing === 0
                ? aggregatedSummary.total === 0
                        ? "No syncs configured yet. Add your first sync below."
                        : "All configured syncs are healthy."
                : "";

        const latestRunText = latestRunInfo
                ? `${latestRunInfo.type} • ${formatDateUtc(latestRunInfo.date)}`
                : "No sync runs have completed yet.";

        const nextScheduledText = nextScheduledInfo
                ? `${nextScheduledInfo.type} • ${formatDateUtc(nextScheduledInfo.date)}`
                : "No upcoming scheduled runs.";

        const summaryStatusEntries = Object.entries(statusBreakdown || {}).filter(
                ([, count]) => count > 0
        );

        const renderEmptyState = (typeKey) => {
                const meta = SYNC_TYPE_CONFIG[typeKey] || { label: typeKey, emptyLabel: typeKey };
                const label = meta.emptyLabel || meta.label || typeKey;
                return (
                        <p style={emptyStateStyle}>
                                No {label} syncs configured yet. {" "}
                                {canManage ? (
                                        <>
                                                Connect a credential on the {" "}
                                                <Link to="/credentials">Credentials page</Link> and use
                                                the form below to add one.
                                        </>
                                ) : (
                                        <>
                                                Ask an administrator to configure one from the {" "}
                                                <Link to="/credentials">Credentials page</Link>.
                                        </>
                                )}
                        </p>
                );
        };

        return (
                <div style={{ padding: "2rem" }}>
                        <Notifications
                                notifications={notifications}
                                onDismiss={dismiss}
                        />
                        <h2>ChatBot Syncs</h2>
                        {!canManage && user && (
                                <p style={{ marginTop: "1rem", color: "#555" }}>
                                        You have read-only access. Contact an administrator to
                                        manage sync configurations.
                                </p>
                        )}
                        <section style={summaryPanelStyle}>
                                <h3 style={{ marginTop: 0 }}>Sync Summary</h3>
                                <p>
                                        <strong>Total syncs configured:</strong> {aggregatedSummary.total}
                                </p>
                                <p>
                                        <strong>Currently failing:</strong> {aggregatedSummary.failing}
                                </p>
                                <p>
                                        <strong>Active jobs:</strong> {aggregatedSummary.running}
                                </p>
                                <p>
                                        <strong>Most recent sync:</strong> {latestRunText}
                                </p>
                                <p>
                                        <strong>Next scheduled run:</strong> {nextScheduledText}
                                </p>
                                <div>
                                        <strong>Per source:</strong>
                                        <ul style={summaryListStyle}>
                                                {typeSummariesInOrder.map((typeInfo) => (
                                                        <li key={typeInfo.key}>
                                                                {typeInfo.label}: {typeInfo.total} configured
                                                                {typeInfo.failing ? ` • ${typeInfo.failing} failing` : ""}
                                                                {typeInfo.running ? ` • ${typeInfo.running} active` : ""}
                                                        </li>
                                                ))}
                                        </ul>
                                </div>
                                {summaryStatusEntries.length > 0 && (
                                        <div>
                                                <strong>Status breakdown:</strong>
                                                <ul style={summaryListStyle}>
                                                        {summaryStatusEntries.map(([status, count]) => (
                                                                <li key={status}>
                                                                        {STATUS_LABELS[status] || status}: {count}
                                                                </li>
                                                        ))}
                                                </ul>
                                        </div>
                                )}
                                {aggregatedSummary.failingSyncs.length > 0 ? (
                                        <div>
                                                <strong>Failing syncs:</strong>
                                                <ul style={summaryListStyle}>
                                                        {aggregatedSummary.failingSyncs.map((item) => (
                                                                <li key={`${item.type}-${item.id}`}>
                                                                        {item.type}: {item.name}
                                                                </li>
                                                        ))}
                                                </ul>
                                        </div>
                                ) : (
                                        healthyMessage && (
                                                <p style={{ margin: "0.5rem 0", color: "#2f855a" }}>
                                                        {healthyMessage}
                                                </p>
                                        )
                                )}
                        </section>
                        <h3>Jira Syncs</h3>
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
                                                const selectedValue = e.target.value;
                                                setNewJira({
                                                        ...newJira,
                                                        credential_id: selectedValue
                                                                ? parseInt(selectedValue, 10)
                                                                : "",
                                                });
                                                setFormMessages((prev) => ({ ...prev, jira: null }));
                                        }}
                                >
                                        <option value="">Select Credential</option>
                                        {credentials.map((cred) => (
                                                <option key={cred.id} value={cred.id}>
                                                        {cred.name}
                                                </option>
                                        ))}
                                </select>
                                {formMessages.jira && (
                                        <p
                                                style={{
                                                        ...inlineMessageBaseStyle,
                                                        color:
                                                                NOTIFICATION_TYPE_COLORS[
                                                                        formMessages.jira.type
                                                                ] || NOTIFICATION_TYPE_COLORS.error,
                                                }}
                                        >
                                                {formMessages.jira.message}
                                        </p>
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

                        {jiraSyncs.length > 0 ? (
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
											credential_id: parseInt(e.target.value, 10),
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
								<button type="button" onClick={() => setEditingJira(null)}>
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
                                                                                                board_url: sync.board_url,
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
								<span style={{ marginLeft: "0.5rem" }}>Checking status...</span>
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
                        ) : (
                                renderEmptyState("jira")
                        )}

                        <h3>Confluence Syncs</h3>
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
                                                        const selectedValue = e.target.value;
                                                        setNewConfluence({
                                                                ...newConfluence,
                                                                credential_id: selectedValue
                                                                        ? parseInt(selectedValue, 10)
                                                                        : "",
                                                        });
                                                        setFormMessages((prev) => ({
                                                                ...prev,
                                                                confluence: null,
                                                        }));
                                                }}
                                        >
                                                <option value="">Select Credential</option>
                                                {credentials.map((cred) => (
                                                        <option key={cred.id} value={cred.id}>
                                                                {cred.name}
                                                        </option>
                                                ))}
                                        </select>
                                        {formMessages.confluence && (
                                                <p
                                                        style={{
                                                                ...inlineMessageBaseStyle,
                                                                color:
                                                                        NOTIFICATION_TYPE_COLORS[
                                                                                formMessages.confluence.type
                                                                        ] || NOTIFICATION_TYPE_COLORS.error,
                                                        }}
                                                >
                                                        {formMessages.confluence.message}
                                                </p>
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

                        {confluenceSyncs.length > 0 ? (
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
											credential_id: parseInt(e.target.value, 10),
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
                                                                                                space_url: sync.space_url,
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
								<span style={{ marginLeft: "0.5rem" }}>Checking status...</span>
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
                                                                <button
                                                                        onClick={() => deleteConfluence(sync.id)}
                                                                >
                                                                        Delete
                                                                </button>
                                                                <button
                                                                        onClick={() => syncConfluenceNow(sync.id)}
                                                                >
                                                                        Sync Now
                                                                </button>
                                                        </>
                                                )}
					</li>
                                ))}
                                </ul>
                        ) : (
                                renderEmptyState("confluence")
                        )}

                        <h3>Git Repository Syncs</h3>
                        {canManage && (
                                <form onSubmit={submitGit}>
                                        <input
                                                placeholder="Repo Full Name (e.g., owner/repo)"
                                                value={newGit.repo_full_name}
                                                onChange={(e) =>
                                                        setNewGit({
                                                                ...newGit,
                                                                repo_full_name: e.target.value,
                                                        })
                                                }
                                        />
                                        <input
                                                placeholder="Branch"
                                                value={newGit.branch}
                                                onChange={(e) =>
                                                        setNewGit({ ...newGit, branch: e.target.value })
                                                }
                                        />
                                        <select
                                                value={newGit.credential_id}
                                                onChange={(e) => {
                                                        const selectedValue = e.target.value;
                                                        setNewGit({
                                                                ...newGit,
                                                                credential_id: selectedValue
                                                                        ? parseInt(selectedValue, 10)
                                                                        : "",
                                                        });
                                                        setFormMessages((prev) => ({ ...prev, git: null }));
                                                }}
                                        >
                                                <option value="">Select credential</option>
                                                {gitCredentials.map((c) => (
                                                        <option key={c.id} value={c.id}>
                                                                {c.name}
                                                        </option>
                                                ))}
                                        </select>
                                        {formMessages.git && (
                                                <p
                                                        style={{
                                                                ...inlineMessageBaseStyle,
                                                                color:
                                                                        NOTIFICATION_TYPE_COLORS[
                                                                                formMessages.git.type
                                                                        ] || NOTIFICATION_TYPE_COLORS.error,
                                                        }}
                                                >
                                                        {formMessages.git.message}
                                                </p>
                                        )}
                                        <select
                                                value={newGit.sync_interval}
                                                onChange={(e) =>
                                                        setNewGit({
                                                                ...newGit,
                                                                sync_interval: e.target.value,
                                                        })
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
                        {gitSyncs.length > 0 ? (
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
                                                                                                sync_interval: sync.sync_interval,
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
                        ) : (
                                renderEmptyState("git")
                        )}
		</div>
	);
}

export default ChatBotSyncs;
