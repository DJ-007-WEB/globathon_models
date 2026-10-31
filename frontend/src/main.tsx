import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/manrope/600.css";
import "@fontsource/manrope/700.css";
import "@fontsource/manrope/800.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/marketing.css";
import "./styles/app.css";
import { ThemeProvider } from "./state/ThemeContext";
import { AuthProvider } from "./state/AuthContext";
import { AuthModal } from "./auth/AuthModal";
import { MarketingLayout } from "./marketing/MarketingLayout";
import { Home } from "./marketing/pages/Home";
import { Capabilities } from "./marketing/pages/Capabilities";
import { Trust } from "./marketing/pages/Trust";
import { Demo } from "./marketing/pages/Demo";
import { Resources } from "./marketing/pages/Resources";
import { About } from "./marketing/pages/About";
import { Contact, NotFound } from "./marketing/pages/Contact";
import { WorkspaceShell } from "./workspace/Shell";
import { Overview } from "./workspace/pages/Overview";
import { Upload } from "./workspace/pages/Upload";
import { Reports } from "./workspace/pages/Reports";
import { ReportDetail } from "./workspace/pages/ReportDetail";
import { Assistant } from "./workspace/pages/Assistant";
import { Plants } from "./workspace/pages/Plants";
import { Validation } from "./workspace/pages/Validation";

const workspaceRoutes = (
  <>
    <Route index element={<Overview />} />
    <Route path="upload" element={<Upload />} />
    <Route path="reports" element={<Reports />} />
    <Route path="reports/:requestId" element={<ReportDetail />} />
    <Route path="assistant" element={<Assistant />} />
    <Route path="plants" element={<Plants />} />
    <Route path="validation" element={<Validation />} />
  </>
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <Routes>
            <Route element={<MarketingLayout />}>
              <Route index element={<Home />} />
              <Route path="capabilities" element={<Capabilities />} />
              <Route path="trust" element={<Trust />} />
              <Route path="demo" element={<Demo />} />
              <Route path="resources" element={<Resources />} />
              <Route path="resources/:slug" element={<Resources />} />
              <Route path="about" element={<About />} />
              <Route path="contact" element={<Contact />} />
              <Route path="*" element={<NotFound />} />
            </Route>
            <Route path="app" element={<WorkspaceShell mode="live" />}>{workspaceRoutes}</Route>
            <Route path="preview" element={<WorkspaceShell mode="preview" />}>{workspaceRoutes}</Route>
          </Routes>
          <AuthModal />
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  </StrictMode>,
);
