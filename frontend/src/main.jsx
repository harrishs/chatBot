import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute.jsx";
import Login from "./pages/Login.jsx";
import ChatBots from "./pages/ChatBots.jsx";
import Credentials from "./pages/Credentials.jsx";
import Navbar from "./components/NavBar.jsx";
import ChatBotSyncs from "./pages/ChatBotSyncs.jsx";

createRoot(document.getElementById("root")).render(
	<StrictMode>
		<BrowserRouter>
			<Navbar />
			<Routes>
				<Route path="/login" element={<Login />} />
				<Route
					path="/"
					element={
						<ProtectedRoute>
							<App />
						</ProtectedRoute>
					}
				/>
				<Route
					path="/chatbots"
					element={
						<ProtectedRoute>
							<ChatBots />
						</ProtectedRoute>
					}
				/>
				<Route
					path="/credentials"
					element={
						<ProtectedRoute>
							<Credentials />
						</ProtectedRoute>
					}
				/>
				<Route
					path="/chatbots/:chatBotId/syncs"
					element={
						<ProtectedRoute>
							<ChatBotSyncs />
						</ProtectedRoute>
					}
				/>
			</Routes>
		</BrowserRouter>
	</StrictMode>
);
