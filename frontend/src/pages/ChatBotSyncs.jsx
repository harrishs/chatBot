import { useEffect, useState } from "react";
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

	const loadData = async () => {
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
	};

	useEffect(() => {
		loadData();
	}, [chatBotId]);

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
		await api.post(`/chatBots/${chatBotId}/jiraSyncs/${id}/sync_now/`);
		loadData();
	};

	const syncConfluenceNow = async (id) => {
		await api.post(`/chatBots/${chatBotId}/confluenceSyncs/${id}/sync_now/`);
		loadData();
	};

	const syncGitNow = async (id) => {
		await api.post(`/chatBots/${chatBotId}/gitRepoSyncs/${id}/sync_now/`);
		loadData();
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
						<button onClick={() => deleteGit(sync.id)}>Delete</button>
						<button onClick={() => syncGitNow(sync.id)}>Sync Now</button>
					</li>
				))}
			</ul>
		</div>
	);
}

export default ChatBotSyncs;
