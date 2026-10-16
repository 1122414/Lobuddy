import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';
import './companion.css';
import { PetSurface, QuickChat } from './companion';
const surface = new URLSearchParams(location.search).get('surface');
document.documentElement.dataset.surface = surface || 'manage';
createRoot(document.getElementById('root')!).render(surface === 'pet' ? <PetSurface /> : surface === 'quick' ? <QuickChat /> : <App />);
