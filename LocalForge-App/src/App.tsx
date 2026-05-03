import { useEffect } from "react";
import {
  IonApp, IonRouterOutlet, IonMenu, IonContent, IonList,
  IonItem, IonIcon, IonLabel, IonMenuToggle, IonHeader,
  IonToolbar, setupIonicReact,
} from "@ionic/react";
import { IonReactRouter } from "@ionic/react-router";
import { Route, Redirect } from "react-router-dom";
import { chatbubbleOutline, addOutline, logOutOutline } from "ionicons/icons";

import { Login } from "./pages/Login";
import { Chat } from "./pages/Chat";
import { Conversations } from "./pages/Conversations";
import { loadServerConfig, checkHealth, clearServerConfig } from "./api/client";
import { useAppStore } from "./store/app";

import "@ionic/react/css/core.css";
import "@ionic/react/css/normalize.css";
import "@ionic/react/css/structure.css";
import "@ionic/react/css/typography.css";

setupIonicReact({ mode: "ios" });

const App: React.FC = () => {
  const isLoggedIn      = useAppStore(s => s.isLoggedIn);
  const setLoggedIn     = useAppStore(s => s.setLoggedIn);
  const setMessages     = useAppStore(s => s.setMessages);
  const setActiveConvId = useAppStore(s => s.setActiveConvId);

  // Auto-login if config saved
  useEffect(() => {
    const cfg = loadServerConfig();
    if (cfg) {
      checkHealth().then(ok => {
        if (ok) setLoggedIn(true, cfg.url);
      });
    }
  }, []);

  const handleLogout = () => {
    clearServerConfig();
    setLoggedIn(false);
    setMessages([]);
    setActiveConvId(null);
  };

  if (!isLoggedIn) {
    return (
      <IonApp>
        <IonReactRouter>
          <IonRouterOutlet>
            <Route exact path="/" component={Login} />
            <Redirect to="/" />
          </IonRouterOutlet>
        </IonReactRouter>
      </IonApp>
    );
  }

  return (
    <IonApp>
      <IonReactRouter>
        <IonMenu contentId="main-content" style={{ "--background": "#1c1c1e", "--width": "260px" } as any}>
          <IonHeader>
            <IonToolbar style={{ "--background": "#1c1c1e", "--color": "#fff" } as any}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "8px 16px" }}>
                <div style={{
                  width: 32, height: 32, borderRadius: 8,
                  background: "linear-gradient(135deg, #10b981, #059669)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 18,
                }}>🔨</div>
                <span style={{ fontWeight: 700, fontSize: 16, color: "#fff" }}>LocalForge</span>
              </div>
            </IonToolbar>
          </IonHeader>

          <IonContent style={{ "--background": "#1c1c1e" } as any}>
            <IonList style={{ background: "transparent", padding: "8px" }}>
              <IonMenuToggle autoHide={false}>
                <IonItem
                  routerLink="/chat"
                  detail={false}
                  button
                  onClick={() => { setMessages([]); setActiveConvId(null); }}
                  style={{ "--background": "transparent", "--color": "#e4e4e7", "--border-radius": "10px", marginBottom: 2 } as any}
                >
                  <IonIcon icon={addOutline} slot="start" style={{ color: "#10b981", fontSize: 20 }} />
                  <IonLabel style={{ fontSize: 14 }}>Nuevo chat</IonLabel>
                </IonItem>
              </IonMenuToggle>

              <IonMenuToggle autoHide={false}>
                <IonItem
                  routerLink="/conversations"
                  detail={false}
                  button
                  style={{ "--background": "transparent", "--color": "#e4e4e7", "--border-radius": "10px", marginBottom: 2 } as any}
                >
                  <IonIcon icon={chatbubbleOutline} slot="start" style={{ color: "#10b981", fontSize: 20 }} />
                  <IonLabel style={{ fontSize: 14 }}>Conversaciones</IonLabel>
                </IonItem>
              </IonMenuToggle>
            </IonList>

            <div style={{ position: "absolute", bottom: 32, left: 0, right: 0, padding: "0 8px" }}>
              <IonMenuToggle autoHide={false}>
                <IonItem
                  button
                  detail={false}
                  onClick={handleLogout}
                  style={{ "--background": "transparent", "--color": "#ef4444", "--border-radius": "10px" } as any}
                >
                  <IonIcon icon={logOutOutline} slot="start" style={{ color: "#ef4444", fontSize: 20 }} />
                  <IonLabel style={{ fontSize: 14 }}>Desconectar</IonLabel>
                </IonItem>
              </IonMenuToggle>
            </div>
          </IonContent>
        </IonMenu>

        <IonRouterOutlet id="main-content">
          <Route exact path="/chat"          component={Chat} />
          <Route exact path="/conversations" component={Conversations} />
          <Redirect exact from="/" to="/chat" />
        </IonRouterOutlet>
      </IonReactRouter>
    </IonApp>
  );
};

export default App;
