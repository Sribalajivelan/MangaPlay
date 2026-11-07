import { Link, Route, Routes } from "react-router-dom";
import { Home } from "./pages/Home";
import { MangaPage } from "./pages/MangaPage";
import { ReadPage } from "./pages/ReadPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/manga/:mangaId" element={<MangaPage />} />
      <Route path="/read/:chapterId" element={<ReadPage />} />
      <Route
        path="*"
        element={
          <main className="page">
            <h1>Page not found</h1>
            <Link to="/">Back to the library</Link>
          </main>
        }
      />
    </Routes>
  );
}
