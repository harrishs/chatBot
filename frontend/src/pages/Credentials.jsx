import { useEffect, useState } from "react";
import api from "../api/axios";
import { useAuth } from "../context/AuthContext.jsx";

function Credentials() {
        const [name, setName] = useState("");
        const [apiKey, setApiKey] = useState("");
        const [credentials, setCredentials] = useState([]);
        const [email, setEmail] = useState("");
	const [editId, setEditId] = useState(null);
        const [gitCreds, setGitCreds] = useState([]);
        const [newGitCred, setNewGitCred] = useState({
                name: "",
                github_username: "",
                token: "",
        });
        const [editGitId, setEditGitId] = useState(null);
        const { user } = useAuth();
        const canManage = user?.is_staff || user?.role === "admin";

	const fetchCredentials = async () => {
		try {
			const res = await api.get("/credentials/");
			setCredentials(res.data);
			const gitRes = await api.get("/gitCredentials/");
			setGitCreds(gitRes.data);
		} catch (err) {
			console.error("Error fetching credentials:", err);
		}
	};

        useEffect(() => {
                fetchCredentials();
        }, []);

        useEffect(() => {
                if (!canManage) {
                        setEditId(null);
                        setEditGitId(null);
                        setName("");
                        setApiKey("");
                        setEmail("");
                        setNewGitCred({ name: "", github_username: "", token: "" });
                }
        }, [canManage]);

        const handleSubmit = async (e) => {
                e.preventDefault();
                if (!canManage) return;
                try {
                        if (editId) {
                                await api.put(`/credentials/${editId}/`, {
                                        name: name,
					api_key: apiKey,
					email: email,
				});
			} else {
				await api.post("/credentials/", {
					name: name,
					api_key: apiKey,
					email: email,
				});
			}
			setName("");
			setApiKey("");
			setEmail("");
			setEditId(null);

			fetchCredentials();
		} catch (err) {
			console.error("Failed to save credentials:", err);
		}
	};

        const handleGitSubmit = async (e) => {
                e.preventDefault();
                if (!canManage) return;
                if (editGitId) {
                        await api.put(`/gitCredentials/${editGitId}/`, newGitCred);
                        setEditGitId(null);
                } else {
                        await api.post("/gitCredentials/", newGitCred);
		}
		setNewGitCred({ name: "", github_username: "", token: "" });
		setGitCreds((await api.get("/gitCredentials/")).data);
	};

        const handleDelete = async (id) => {
                if (!canManage) return;
                if (!window.confirm("Are you sure you want to delete this credential?"))
                        return;
                try {
                        await api.delete(`/credentials/${id}/`);
			setName("");
			setApiKey("");
			setEmail("");
			setEditId(null);
			fetchCredentials();
		} catch (err) {
			console.error("Failed to delete credential:", err);
		}
	};

        const handleGitDelete = async (id) => {
                if (!canManage) return;
                if (!window.confirm("Are you sure you want to delete this credential?"))
                        return;
                try {
                        await api.delete(`/gitCredentials/${id}/`);
			setNewGitCred({ name: "", github_username: "", token: "" });
			fetchCredentials();
		} catch (err) {
			console.error("Failed to delete credential:", err);
		}
	};

        const handleEdit = (cred) => {
                if (!canManage) return;
                setName(cred.name);
                setEmail(cred.email);
                setEditId(cred.id);
                //Api key not available as it is write-only, user must re-enter it
                setApiKey("");
        };

        const handleGitEdit = (cred) => {
                if (!canManage) return;
                setEditGitId(cred.id);
                setNewGitCred({
                        name: cred.name,
                        github_username: cred.github_username,
			token: "",
		});
	};

        return (
                <div style={{ padding: "2rem" }}>
                        <h2>Credentials</h2>
                        {!canManage && user && (
                                <p style={{ marginTop: "1rem", color: "#555" }}>
                                        You have read-only access. Contact an administrator to
                                        manage credentials.
                                </p>
                        )}

                        {canManage && (
                                <>
                                        <h3>
                                                {editId
                                                        ? "Edit Atlassian API Credential"
                                                        : "Create a New Atlassian API Credential"}
                                        </h3>
                                        <form
                                                onSubmit={handleSubmit}
                                                style={{ marginBottom: "2rem" }}
                                        >
                                                <div>
                                                        <label>Name (Label for this key):</label>
                                                        <br />
                                                        <input
                                                                type="text"
                                                                value={name}
                                                                onChange={(e) => setName(e.target.value)}
                                                                required
                                                        />
                                                </div>
                                                <div>
                                                        <label>API Email:</label>
                                                        <br />
                                                        <input
                                                                type="email"
                                                                value={email}
                                                                onChange={(e) => setEmail(e.target.value)}
                                                                required
                                                        />
                                                </div>
                                                <div>
                                                        <label>API Key:</label>
                                                        <br />
                                                        <input
                                                                type="password"
                                                                autoComplete="off"
                                                                value={apiKey}
                                                                onChange={(e) => setApiKey(e.target.value)}
                                                                required
                                                                placeholder={
                                                                        editId
                                                                                ? "Enter New/ Existing Key"
                                                                                : ""
                                                                }
                                                        />
                                                </div>
                                                <button type="submit">
                                                        {editId ? "Update" : "Save"} Credential
                                                </button>
                                                {editId && (
                                                        <button
                                                                type="button"
                                                                style={{ marginLeft: "1rem" }}
                                                                onClick={() => {
                                                                        setEditId(null);
                                                                        setName("");
                                                                        setApiKey("");
                                                                        setEmail("");
                                                                }}
                                                        >
                                                                Cancel
                                                        </button>
                                                )}
                                        </form>
                                        <h3>
                                                {editGitId
                                                        ? "Edit Github Credential"
                                                        : "Create a New Github Credential"}
                                        </h3>
                                        <form onSubmit={handleGitSubmit}>
                                                <input
                                                        placeholder="Name"
                                                        value={newGitCred.name}
                                                        onChange={(e) =>
                                                                setNewGitCred({
                                                                        ...newGitCred,
                                                                        name: e.target.value,
                                                                })
                                                        }
                                                />
                                                <input
                                                        placeholder="GitHub Username"
                                                        value={newGitCred.github_username}
                                                        onChange={(e) =>
                                                                setNewGitCred({
                                                                        ...newGitCred,
                                                                        github_username: e.target.value,
                                                                })
                                                        }
                                                />
                                                <input
                                                        placeholder="Token"
                                                        type="password"
                                                        value={newGitCred.token}
                                                        onChange={(e) =>
                                                                setNewGitCred({
                                                                        ...newGitCred,
                                                                        token: e.target.value,
                                                                })
                                                        }
                                                />
                                                <button type="submit">
                                                        {editGitId
                                                                ? "Update Git Credential"
                                                                : "Add Git Credential"}
                                                </button>
                                        </form>
                                </>
                        )}

                        <h3>Existing Atlassian Credentials</h3>
                        <ul>
                                {credentials.map((cred) => (
                                        <li key={cred.id}>
                                                <strong>{cred.name}</strong> — <code>{cred.email}</code>
                                                {canManage && (
                                                        <>
                                                                <br />
                                                                <button onClick={() => handleEdit(cred)}>
                                                                        Edit
                                                                </button>
                                                                <button
                                                                        onClick={() => handleDelete(cred.id)}
                                                                        style={{ marginLeft: "1rem" }}
                                                                >
                                                                        Delete
                                                                </button>
                                                        </>
                                                )}
                                        </li>
                                ))}
                        </ul>
                        <h3>Existing Github Credentials</h3>
                        <ul>
                                {gitCreds.map((cred) => (
                                        <li key={cred.id}>
                                                {cred.name} ({cred.github_username})
                                                {canManage && (
                                                        <>
                                                                <button onClick={() => handleGitEdit(cred)}>
                                                                        Edit
                                                                </button>
                                                                <button onClick={() => handleGitDelete(cred.id)}>
                                                                        Delete
                                                                </button>
                                                        </>
                                                )}
                                        </li>
                                ))}
                        </ul>
                </div>
        );
}

export default Credentials;
