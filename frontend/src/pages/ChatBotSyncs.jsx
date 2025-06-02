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
		console.log("Submitting Jira sync:", newJira);
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
		console.log("Submitting Confluence sync:", newConfluence);
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
						{sync.board_url} (Credential: {sync.credential?.name})
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
						{sync.space_url} (Credential: {sync.credential?.name})
						<button onClick={() => deleteConfluence(sync.id)}>Delete</button>
					</li>
				))}
			</ul>
		</div>
	);
}

export default ChatBotSyncs;
