import {
  IonButton, IonIcon, IonSelect, IonSelectOption,
} from "@ionic/react";
import { hardwareChipOutline } from "ionicons/icons";
import type { Model } from "../api/client";

interface Props {
  models: Model[];
  value: string;
  onChange: (name: string) => void;
}

export const ModelPicker: React.FC<Props> = ({ models, value, onChange }) => {
  if (models.length === 0) return null;

  return (
    <IonSelect
      value={value}
      onIonChange={e => onChange(e.detail.value)}
      interface="action-sheet"
      placeholder="Modelo"
      style={{
        "--color": "#10b981",
        fontSize: 12,
        maxWidth: 140,
      }}
    >
      {models.map(m => (
        <IonSelectOption key={m.name} value={m.name}>
          {m.display_name}
        </IonSelectOption>
      ))}
    </IonSelect>
  );
};
