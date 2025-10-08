import { useEffect, useState } from "react";
import api from "./api/axios";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./context/AuthContext.jsx";

function App() {
        const [users, setUsers] = useState([]);
        const navigate = useNavigate();
        const { logout, user } = useAuth();

        useEffect(() => {
                if (!user) {
                        setUsers([]);
                        return;
                }

                const fetchUsers = async () => {
                        try {
                                const res = await api.get("/users/");
                                setUsers(res.data);
                        } catch (err) {
                                console.error("Error fetching users:", err);
                        }
                };

                fetchUsers();
        }, [user]);

        const handleLogout = async () => {
                try {
                        await logout();
                } catch (error) {
                        console.error("Failed to log out:", error);
                } finally {
                        navigate("/login");
                }
        };

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
