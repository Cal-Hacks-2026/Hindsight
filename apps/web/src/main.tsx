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
import { Home } from "./routes/Home";
import { Landing } from "./routes/Landing";
import { Schedule } from "./routes/Schedule";
import { University } from "./routes/University";
import { loadSession } from "./lib/session";
import "./styles/tokens.css";
import "./styles/app.css";

// Home once there's a profile, the landing page before that.
function Start() {
  return loadSession().profile ? <Home /> : <Landing />;
}

function PreviousPlan() {
  const { state } = useLocation();
  return <Navigate to="/plan" state={state} replace />;
}

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Start /> },
      { path: "/onboarding", element: <Onboarding /> },
      { path: "/plan", element: <Degree view="plan" /> },
      { path: "/credits", element: <Degree view="credits" /> },
      { path: "/degree", element: <PreviousPlan /> },
      { path: "/schedule", element: <Schedule /> },
      { path: "/radar", element: <Radar /> },
      { path: "/university", element: <University /> },
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
