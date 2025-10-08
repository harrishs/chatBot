import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

function Navbar() {
        const { user, initializing } = useAuth();

        if (initializing || !user) {
                return null;
        }

        return (
                <nav
                        style={{
                                padding: "1rem",
                                background: "#f0f0f0",
                                borderBottom: "1px solid #ccc",
                                display: "flex",
                                gap: "1rem",
                        }}
                >
                        <Link to="/">Home</Link>
                        <Link to="/chatbots">Chatbots</Link>
                        <Link to="/credentials">Credentials</Link>
                </nav>
        );
}

export default Navbar;
