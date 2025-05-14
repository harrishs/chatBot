import { useEffect, useState } from "react";
import Login from "./pages/Login";
import api from "./api/axios";

function App() {
	const [users, setUsers] = useState([]);
	const [loggedIn, setLoggedIn] = useState(!!localStorage.getItem("authToken"));

	const fetchUsers = async () => {
		try {
			const res = await api.get("/users/");
			setUsers(res.data);
		} catch (err) {
			console.error("Error fetching users:", err);
		}
	};

	useEffect(() => {
		if (loggedIn) {
			fetchUsers();
		}
	}, [loggedIn]);

	const handleLogout = () => {
		localStorage.removeItem("authToken");
		setLoggedIn(false);
	};

	if (!loggedIn) return <Login onLogin={() => setLoggedIn(true)} />;

	return (
		<div style={{ padding: "2rem" }}>
			<h2>Users in Your Company</h2>
			<button onClick={handleLogout}>Logout</button>
			<ul>
				{users.map((u) => (
					<li key={u.id}>
						{u.username} ({u.email})
					</li>
				))}
			</ul>
		</div>
	);
}

export default App;
