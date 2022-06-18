import argparse
import pickle
from pathlib import Path
from typing import List, Optional, Tuple

import cv2  # pytype: disable=import-error
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from ae.autoencoder import Autoencoder, load_ae


def prepare_datasets(
    autoencoder: Autoencoder,
    folders: List[str],
    normalize: bool = False,
    ae_mask: Optional[Autoencoder] = None,
    weight_autoencoder: float = 1,
    weight_ae_mask: float = 1,
    weight_cte: float = 10,
) -> Tuple[List[np.ndarray], List[List[str]]]:
    datasets = []
    names = []
    for folder in folders:
        with open(Path(folder) / "infos.pkl", "rb") as f:
            infos = pickle.load(f)

        # Preprocess and create features
        maybe_mask_encoder = ae_mask.z_size if ae_mask is not None else 0
        dataset = np.zeros((len(infos), autoencoder.z_size + maybe_mask_encoder + 1))
        for i, (name, info) in enumerate(infos.items()):
            input_image = cv2.imread(str(Path(folder) / f"{name}.jpg"))
            encoded_image = autoencoder.encode_from_raw_image(input_image).flatten()
            dataset[i][: autoencoder.z_size] = encoded_image
            if ae_mask is not None:
                encoded_mask = ae_mask.encode_from_raw_image(input_image).flatten()
                dataset[i][autoencoder.z_size : autoencoder.z_size + ae_mask.z_size] = encoded_mask

            dataset[i][-1] = info["cte"]

        datasets.append(np.array(dataset))
        names.append(list(infos.keys()))

    # Normalize according to first dataset
    normalizer = StandardScaler().fit(datasets[0])
    for i, dataset in enumerate(datasets):
        if normalize:
            datasets[i] = normalizer.transform(dataset)

        datasets[i][:, : autoencoder.z_size] *= weight_autoencoder
        if ae_mask is not None:
            datasets[i][:, autoencoder.z_size : autoencoder.z_size + ae_mask.z_size] *= weight_ae_mask
        # More weight for CTE
        datasets[i][:, -1] *= weight_cte
    return datasets, names


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-f", "--folder", help="Log folders", type=str, nargs="+", required=True)
    parser.add_argument("-ae", "--ae-path", help="Path to saved AE", type=str, required=True)
    parser.add_argument("-ae-mask", "--ae-mask-path", help="Path to saved AE for segmentation", type=str)
    parser.add_argument("-n", "--n-samples", help="Max number of samples", type=int, default=20)
    parser.add_argument("--seed", help="Random generator seed", type=int, default=0)
    parser.add_argument("-cte", "--weight-cte", help="Weight for CTE", type=float, default=10)
    args = parser.parse_args()

    np.random.seed(args.seed)

    autoencoder = load_ae(args.ae_path)
    ae_mask = None
    if args.ae_mask_path is not None:
        ae_mask = load_ae(args.ae_mask_path)

    datasets, names = prepare_datasets(autoencoder, args.folder, ae_mask=ae_mask, weight_cte=args.weight_cte)

    # Create KNN with first dataset
    knn = NearestNeighbors(n_neighbors=2, algorithm="ball_tree").fit(datasets[0])

    other_dataset = datasets[1]
    random_samples = np.random.permutation(len(other_dataset))[: args.n_samples]
    image_grid = []
    for idx, sample in enumerate(random_samples):

        _, neighbor_indices = knn.kneighbors([other_dataset[sample]])
        neighbor_indices = neighbor_indices.flatten()

        image1_path = str(Path(args.folder[1]) / f"{names[1][sample]}.jpg")
        image1 = cv2.imread(image1_path)

        neighbors = []
        for neighbor_idx in neighbor_indices:
            image_path = str(Path(args.folder[0]) / f"{names[0][neighbor_idx]}.jpg")
            neighbor_image = cv2.imread(image_path)
            neighbors.append(neighbor_image)
        image_grid.append(np.hstack([image1] + neighbors))

        if (idx + 1) % 5 == 0:
            grid = np.array(image_grid)
            cv2.imshow("Image grid", grid.reshape((-1,) + grid.shape[2:]))
            # stop if escape is pressed
            k = cv2.waitKey(0) & 0xFF

            if k == 27:
                break
            image_grid = []
