import { useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../api/axios";

function Login() {
	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState("");
	const navigate = useNavigate();

	const handleSubmit = async (e) => {
		e.preventDefault();
		try {
			const res = await api.post("/login/", { username, password });
			localStorage.setItem("authToken", res.data.token);
			navigate("/");
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
