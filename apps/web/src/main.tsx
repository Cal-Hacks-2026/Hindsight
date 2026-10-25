import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  createBrowserRouter,
  Navigate,
  RouterProvider,
  useLocation,
} from "react-router";
import { Layout } from "./components/Layout";
import { Onboarding } from "./routes/Onboarding";
import { Degree } from "./routes/Degree";
import { Radar } from "./routes/Radar";
import { Counselor } from "./routes/Counselor";
import { loadSession } from "./lib/session";
import "./styles/tokens.css";
import "./styles/app.css";

// No home screen of its own: Degree once there's a profile, onboarding before that.
function Home() {
  return (
    <Navigate to={loadSession().profile ? "/plan" : "/onboarding"} replace />
  );
}

function PreviousPlan() {
  const { state } = useLocation();
  return <Navigate to="/plan" state={state} replace />;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Home /> },
      { path: "/onboarding", element: <Onboarding /> },
      { path: "/plan", element: <Degree view="plan" /> },
      { path: "/credits", element: <Degree view="credits" /> },
      { path: "/degree", element: <PreviousPlan /> },
      { path: "/radar", element: <Radar /> },
      { path: "/counselor", element: <Counselor /> },
      { path: "/agent", element: <Navigate to="/plan" replace /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
