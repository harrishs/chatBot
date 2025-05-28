import { Link } from "react-router-dom";

function Navbar() {
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
			{/* Add more as needed */}
		</nav>
	);
}

export default Navbar;
