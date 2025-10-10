import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../api/axios";

function ChatBotSyncs() {
	const { chatBotId } = useParams();

	const [jiraSyncs, setJiraSyncs] = useState([]);
	const [confluenceSyncs, setConfluenceSyncs] = useState([]);
	const [credentials, setCredentials] = useState([]);
	const [gitSyncs, setGitSyncs] = useState([]);
	const [gitCredentials, setGitCredentials] = useState([]);

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
                                                        window.alert(data.job_message || data.message || "Sync failed.");
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
                [chatBotId, loadData, stopPolling, updateSync],
        );

        useEffect(() => {
                loadData();
        }, [loadData]);

        useEffect(() => () => {
                Object.values(pollTimeouts.current).forEach((timeoutId) => {
                        clearTimeout(timeoutId);
                });
                pollTimeouts.current = {};
                activePolls.current = {};
        }, []);

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
                                window.alert("Failed to queue sync job. Please check the configuration and try again.");
                        }
                },
                [chatBotId, pollStatus, updateSync],
        );

	const submitJira = async (e) => {
		e.preventDefault();
		try {
			await api.post(`/chatBots/${chatBotId}/jiraSyncs/`, newJira);
			setNewJira({ board_url: "", credential_id: "", sync_interval: "manual" });
			loadData();
		} catch (err) {
			console.error("Error submitting Jira sync", err);
		}
	};

	const submitConfluence = async (e) => {
		e.preventDefault();
		try {
			await api.post(`/chatBots/${chatBotId}/confluenceSyncs/`, newConfluence);
			setNewConfluence({
				space_url: "",
				credential_id: "",
				sync_interval: "manual",
			});
			loadData();
		} catch (err) {
			console.error("Error submitting Confluence sync", err);
		}
	};

	const submitGit = async (e) => {
		e.preventDefault();
		await api.post(`/chatBots/${chatBotId}/gitRepoSyncs/`, {
			...newGit,
			credential_id: parseInt(newGit.credential_id, 10),
		});
		setNewGit({
			repo_full_name: "",
			branch: "main",
			credential_id: "",
			sync_interval: "manual",
		});
		loadData();
	};

	const deleteJira = async (id) => {
		await api.delete(`/chatBots/${chatBotId}/jiraSyncs/${id}/`);
		loadData();
	};

	const deleteConfluence = async (id) => {
		await api.delete(`/chatBots/${chatBotId}/confluenceSyncs/${id}/`);
		loadData();
	};

	const deleteGit = async (id) => {
		await api.delete(`/chatBots/${chatBotId}/gitRepoSyncs/${id}/`);
		loadData();
	};

	const editJira = async (e) => {
		e.preventDefault();
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

        return (
                <div style={{ padding: "2rem" }}>
			<h2>Jira Syncs</h2>
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
					onChange={(e) =>
						setNewJira({
							...newJira,
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

			<ul>
				{jiraSyncs.map((sync) => (
					<li key={sync.id}>
						{editingJira === sync.id ? (
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
                                                                <button
                                                                        onClick={() => {
                                                                                setEditingJira(sync.id);
                                                                                setEditingJiraData({
                                                                                        board_url: sync.board_url,
											credential_id: sync.credential?.id,
											sync_interval: sync.sync_interval,
										});
									}}
								>
									Edit
								</button>
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
                                                {sync.sync_status_message && (
                                                        <div>{sync.sync_status_message}</div>
                                                )}
                                                {jobDetails[makeJobKey("jira", sync.id)]?.jobMessage && (
                                                        <div>
                                                                <em>
                                                                        Job message: {
                                                                                jobDetails[makeJobKey("jira", sync.id)]
                                                                                        ?.jobMessage
                                                                        }
                                                                </em>
                                                        </div>
                                                )}
                                                <button onClick={() => deleteJira(sync.id)}>Delete</button>
                                                <button onClick={() => syncJiraNow(sync.id)}>Sync Now</button>
                                        </li>
                                ))}
                        </ul>

			<h2>Confluence Syncs</h2>
			<form onSubmit={submitConfluence}>
				<input
					placeholder="Confluence Space URL"
					value={newConfluence.space_url}
					onChange={(e) =>
						setNewConfluence({ ...newConfluence, space_url: e.target.value })
					}
				/>
				<select
					value={newConfluence.credential_id}
					onChange={(e) =>
						setNewConfluence({
							...newConfluence,
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

			<ul>
				{confluenceSyncs.map((sync) => (
					<li key={sync.id}>
						{editingConfluence === sync.id ? (
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
                                                                <button
                                                                        onClick={() => {
                                                                                setEditingConfluence(sync.id);
                                                                                setEditingConfluenceData({
                                                                                        space_url: sync.space_url,
											credential_id: sync.credential?.id,
											sync_interval: sync.sync_interval,
										});
									}}
								>
									Edit
								</button>
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
                                                {sync.sync_status_message && (
                                                        <div>{sync.sync_status_message}</div>
                                                )}
                                                {jobDetails[makeJobKey("confluence", sync.id)]?.jobMessage && (
                                                        <div>
                                                                <em>
                                                                        Job message: {
                                                                                jobDetails[makeJobKey("confluence", sync.id)]
                                                                                        ?.jobMessage
                                                                        }
                                                                </em>
                                                        </div>
                                                )}
                                                <button onClick={() => deleteConfluence(sync.id)}>Delete</button>
                                                <button onClick={() => syncConfluenceNow(sync.id)}>Sync Now</button>
                                        </li>
                                ))}
                        </ul>

			<h2>Git Repository Syncs</h2>
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
					onChange={(e) =>
						setNewGit({
							...newGit,
							credential_id: parseInt(e.target.value, 10),
						})
					}
				>
					<option value="">Select credential</option>
					{gitCredentials.map((c) => (
						<option key={c.id} value={c.id}>
							{c.name}
						</option>
					))}
				</select>
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
			<ul>
				{gitSyncs.map((sync) => (
					<li key={sync.id}>
						{editingGit === sync.id ? (
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
                                                                <button
                                                                        onClick={() => {
                                                                                setEditingGit(sync.id);
                                                                                setEditingGitData({
                                                                                        repo_full_name: sync.repo_full_name,
											branch: sync.branch,
											credential_id: parseInt(sync.credential?.id),
											sync_interval: sync.sync_interval,
										});
									}}
								>
									Edit
								</button>
							</>
						)}
                                                <div>
                                                        <strong>Status:</strong> {sync.sync_status || "idle"}
                                                        {jobDetails[makeJobKey("git", sync.id)]?.isPolling && (
                                                                <span style={{ marginLeft: "0.5rem" }}>
                                                                        Checking status...
                                                                </span>
                                                        )}
                                                </div>
                                                {sync.sync_status_message && (
                                                        <div>{sync.sync_status_message}</div>
                                                )}
                                                {jobDetails[makeJobKey("git", sync.id)]?.jobMessage && (
                                                        <div>
                                                                <em>
                                                                        Job message: {
                                                                                jobDetails[makeJobKey("git", sync.id)]
                                                                                        ?.jobMessage
                                                                        }
                                                                </em>
                                                        </div>
                                                )}
                                                <button onClick={() => deleteGit(sync.id)}>Delete</button>
                                                <button onClick={() => syncGitNow(sync.id)}>Sync Now</button>
                                        </li>
                                ))}
                        </ul>
		</div>
	);
}

export default ChatBotSyncs;
