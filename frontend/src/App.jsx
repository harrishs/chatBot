import { useEffect, useState } from "react";
import api from "./api/axios";
import { useNavigate, Link } from "react-router-dom";

function App() {
	const [users, setUsers] = useState([]);
	const navigate = useNavigate();

	const fetchUsers = async () => {
		try {
			const res = await api.get("/users/");
			setUsers(res.data);
		} catch (err) {
			console.error("Error fetching users:", err);
		}
	};

	useEffect(() => {
		fetchUsers();
	}, []);

	const handleLogout = () => {
		localStorage.removeItem("authToken");
		navigate("/login");
	};

	return (
		<div style={{ padding: "2rem" }}>
			<h2>Users in Your Company</h2>
			<Link to="/chatbots"> Manage ChatBots</Link>
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
