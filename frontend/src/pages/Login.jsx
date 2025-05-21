import { useState } from "react";
import api from "../api/axios";

function Login({ onLogin }) {
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState("");

	const handleSubmit = async (e) => {
		try {
			e.preventDefault();
			const res = await api.post("/login/", { username, password });
			localStorage.setItem("authToken", res.data.token);
			onLogin();
		} catch (err) {
			setError("Invalid Credentials");
		}
	};

	return (
		<div style={{ padding: "2rem" }}>
			<h2>Login</h2>
			<form onSubmit={handleSubmit}>
				<div>
					<label>Username:</label>
					<br />
					<input
						value={username}
						onChange={(e) => setUsername(e.target.value)}
						required
					/>
				</div>
				<div>
					<label>Password:</label>
					<br />
					<input
						type="password"
						value={password}
						onChange={(e) => setPassword(e.target.value)}
						required
					/>
				</div>
				<button type="submit">Login</button>
				{error && <p style={{ color: "red" }}>{error}</p>}
			</form>
		</div>
	);
}

export default Login;
