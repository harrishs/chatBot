import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import api from "../api/axios";

function ChatBotSyncs() {
	const { chatBotId } = useParams();

	const [jiraSyncs, setJiraSyncs] = useState([]);
	const [confluenceSyncs, setConfluenceSyncs] = useState([]);
	const [credentials, setCredentials] = useState([]);

	const [newJira, setNewJira] = useState({ board_url: "", credential_id: "" });
	const [newConfluence, setNewConfluence] = useState({
		space_url: "",
		credential_id: "",
	});

	const [editingJira, setEditingJira] = useState(null);
	const [editingConfluence, setEditingConfluence] = useState(null);
	const [editingJiraData, setEditingJiraData] = useState({
		board_url: "",
		credential_id: "",
	});
	const [editingConfluenceData, setEditingConfluenceData] = useState({
		space_url: "",
		credential_id: "",
	});

	const loadData = async () => {
		try {
			const [jiraRes, confRes, credRes] = await Promise.all([
				api.get(`/chatBots/${chatBotId}/jiraSyncs/`),
				api.get(`/chatBots/${chatBotId}/confluenceSyncs/`),
				api.get("/credentials/"),
			]);
			setJiraSyncs(jiraRes.data);
			setConfluenceSyncs(confRes.data);
			setCredentials(credRes.data);
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
			setNewJira({ board_url: "", credential_id: "" });
			loadData();
		} catch (err) {
			console.error("Error submitting Jira sync", err);
		}
	};

	const submitConfluence = async (e) => {
		e.preventDefault();
		try {
			await api.post(`/chatBots/${chatBotId}/confluenceSyncs/`, newConfluence);
			setNewConfluence({ space_url: "", credential_id: "" });
			loadData();
		} catch (err) {
			console.error("Error submitting Confluence sync", err);
		}
	};

	const deleteJira = async (id) => {
		await api.delete(`/chatBots/${chatBotId}/jiraSyncs/${id}/`);
		loadData();
	};

	const deleteConfluence = async (id) => {
		await api.delete(`/chatBots/${chatBotId}/confluenceSyncs/${id}/`);
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
			setEditingJiraData({ board_url: "", credential_id: "" });
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
			setEditingConfluenceData({ space_url: "", credential_id: "" });
			loadData();
		} catch (err) {
			console.error("Error editing Confluence sync", err);
		}
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
										});
									}}
								>
									Edit
								</button>
							</>
						)}
						<button onClick={() => deleteJira(sync.id)}>Delete</button>
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
										});
									}}
								>
									Edit
								</button>
							</>
						)}
						<button onClick={() => deleteConfluence(sync.id)}>Delete</button>
					</li>
				))}
			</ul>
		</div>
	);
}

export default ChatBotSyncs;
