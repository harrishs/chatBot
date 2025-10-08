import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

function Login() {
        const [username, setUsername] = useState("");
        const [password, setPassword] = useState("");
        const [error, setError] = useState("");
        const [isSubmitting, setIsSubmitting] = useState(false);
        const navigate = useNavigate();
        const { login, user, initializing } = useAuth();

        useEffect(() => {
                if (!initializing && user) {
                        navigate("/");
                }
        }, [initializing, user, navigate]);

        const handleSubmit = async (e) => {
                e.preventDefault();
                setError("");
                setIsSubmitting(true);

                try {
                        await login(username, password);
                        navigate("/");
                } catch (err) {
                        const detail = err.response?.data?.detail || "Invalid credentials";
                        setError(detail);
                } finally {
                        setIsSubmitting(false);
                }
        };

        if (initializing) {
                return null;
        }

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
                                <button type="submit" disabled={isSubmitting}>
                                        {isSubmitting ? "Logging in..." : "Login"}
                                </button>
                                {error && <p style={{ color: "red" }}>{error}</p>}
                        </form>
                </div>
        );
}

export default Login;
