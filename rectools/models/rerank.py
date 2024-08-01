from rectools.models.base import ModelBase, NotFittedError, AnyIds
from rectools.dataset import Dataset
from rectools.dataset.identifiers import ExternalIds
from rectools import Columns
from rectools.model_selection import Splitter
import pandas as pd
import typing as tp
from functools import reduce
import attr
import typing as tp
from numpy.random import default_rng
import numpy as np

@runtime_checkable
class BaseClassifier(tp.Protocol):
    # TODO: this is not final. See details: https://mypy.readthedocs.io/en/stable/protocols.html#defining-subprotocols-and-subclassing-protocols
    def fit(self): ...
    
    def predict_proba(self): ...
    
# TODO: BaseRanker (for CatboostRanker and others like it)

# TODO: add tests with sklearn classifier (and ranker if there is any). we have sklearn in dependencies

# TODO: add CatboostReranker(RerankerBase) (catboost dependecy to  extras?)
    

class RerankerBase:
    def __init__(self, model: tp.Union[BaseClassifier, BaseRanker]):
        self.model = model
        self.is_classifier = isinstance(model, BaseClassifier)
    
    def fit(self, candidates_with_target):
        self.model.fit(candidates_with_target.drop(columns=Columns.UserItem))

    def rerank(self, candidates, k):
        reco = candidates[Columns.UserItem].copy()
        x_full = candidates.drop(columns=Columns.UserItem)
        
        # TODO: think about it
        # x_full = x_full[self.model.feature_names_]
        
        if self.is_classifier:
            reco[Columns.Score] = self.model.predict_proba(x_full)[:, 1]  # TODO: для всех ли классифайеров подходит? sklearn, lightgbm - ?
        else:
            pass  # TODO
        reco.sort_values(by=[Columns.User, Columns.Score], ascending=False, inplace=True)
        reco = reco.groupby(Columns.User).head(k)
        return reco


class CandidatesFeatureCollector:
    """
    Base class for collecting features for candidates user-item pairs. Useful for creating train with features for
    TwoStageModel.
    Using this in TwoStageModel will result in not adding any features at all.
    Inherit from this class and rewrite private methods to grab features from dataset and external sources
    """
    # TODO: create an inherited class that will get all features from dataset?
    
    def _get_user_features(self, users: AnyIds, dataset, fold_info, **kwargs) -> tp.Optional[pd.DataFrame]:
        return None
    def _get_item_features(self, items: AnyIds, dataset, fold_info, **kwargs) -> tp.Optional[pd.DataFrame]:
        return None
    def _get_user_item_features(self, useritem: pd.DataFrame, dataset, fold_info, **kwargs) -> tp.Optional[pd.DataFrame]:
        return None
    def collect_features(self, useritem: pd.DataFrame, dataset: Dataset, fold_info: tp.Optional[tp.Dict[str, tp.Any]], **kwargs) -> pd.DataFrame:
        user_features = self._get_user_features(useritem[Columns.User].unique(), dataset, fold_info, **kwargs)
        item_features = self._get_item_features(useritem[Columns.Item].unique(), dataset, fold_info, **kwargs)
        useritem_features = self._get_user_item_features(useritem, dataset, fold_info, **kwargs)

        res = useritem  # TODO: copy?
        
        if user_features is not None:
            res = res.merge(user_features, on=Columns.User, how="left")
        if item_features is not None:
            res = res.merge(user_features, on=Columns.Item, how="left")
        if useritem_features is not None:
            res = res.merge(useritem_features, on=Columns.UserItem, how="left")
        return res



class NegativeSamplerBase:
    def sample_negatives(self, train: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError()


@attr.s
class PerUserNegativeSampler(NegativeSamplerBase):
    num_neg_samples: int = 3
    random_state: tp.Optional[int] = None

    def sample_negatives(self, train: pd.DataFrame) -> pd.DataFrame:
        # train: user_id, item_id, scores, ranks, target(1/0)
        
        negative_mask = train["target"] == 0
        pos = train[~negative_mask]
        neg = train[negative_mask]
        
        # Some users might not have enough negatives for sampling
        num_negatives = (
            neg
            .groupby([Columns.User])[Columns.Item]
            .count()
        )
        sampling_mask = train[Columns.User].isin(
            num_negatives[num_negatives > self.num_neg_samples].index
        )
        
        neg_for_sample = train[sampling_mask & negative_mask]
        neg = neg_for_sample.groupby([Columns.User], sort=False).apply(
            pd.DataFrame.sample,
            n=self.num_neg_samples,
            replace=False,
            random_state=self.random_state,
        )
        neg = pd.concat([neg, train[(~sampling_mask) & negative_mask]], axis=0)
        sampled_train = pd.concat([neg, pos], ignore_index=True).sample(
            frac=1, random_state=self.random_state
        )

        return sampled_train


# class PerPosNegativeSampler(NegativeSamplerBase):
#     num_neg_samples: int = 3
#     user_max_neg_samples: int = 25
#     random_state: tp.Optional[int] = None

#     def sample_negatives(self, train: pd.DataFrame) -> pd.DataFrame:
#         # train: user_id, item_id, scores, ranks, target(1/0)
        
#         negative_mask = train["target"] == 0
#         pos = train[~negative_mask]
#         neg = train[negative_mask]
#         train["id"] = train.index
        
#         num_positives = pos.groupby("user_id")["item_id"].count()
#         num_positives.name = "num_positives"

#         num_negatives = neg.groupby("user_id")["item_id"].count()
#         num_negatives.name = "num_negatives"
        
#         neg_sampling = pd.DataFrame(neg.groupby("user_id")["id"].apply(list)).join(
#             num_positives, on="user_id", how="left"
#         )
#         neg_sampling = neg_sampling.join(num_negatives, on="user_id", how="left")
#         neg_sampling["num_negatives"] = (
#             neg_sampling["num_negatives"].fillna(0).astype("int32")
#         )
#         neg_sampling["num_positives"] = (
#             neg_sampling["num_positives"].fillna(0).astype("int32")
#         )
#         neg_sampling["num_choices"] = np.clip(
#             neg_sampling["num_positives"] * self.num_neg_samples,
#             a_min=0,
#             a_max=self.user_max_neg_samples,
#         )

#         rng = default_rng(self.random_state)
#         neg_sampling["sampled_idx"] = neg_sampling.apply(
#             lambda row: rng.choice(
#                 row["id"],
#                 size=min(row["num_choices"], row["num_negatives"]),
#                 replace=False,
#             ),
#             axis=1,
#         )
#         idx_chosen = neg_sampling["sampled_idx"].explode().values
#         neg = neg[neg["id"].isin(idx_chosen)].drop(columns="id")

#         sampled_train = pd.concat([neg, pos], ignore_index=True).sample(
#             frac=1, random_state=self.random_state
#         ).drop(columns="id")
        
#         return sampled_train


class CandidateGenerator:
    def __init__(
        self,
        model: ModelBase,
        num_candidates: int,
        keep_ranks: bool,
        keep_scores: bool,
        scores_fillna_value: tp.Optional[float] = None,
        ranks_fillna_value: tp.Optional[float] = None,
    ):
        self.model = model
        self.num_candidates = num_candidates
        self.keep_ranks = keep_ranks
        self.keep_scores = keep_scores
        self.scores_fillna_value = scores_fillna_value
        self.ranks_fillna_value = ranks_fillna_value
        self.is_fitted_for_train = False
        self.is_fitted_for_recommend = False

    def fit(self, dataset: Dataset, for_train: bool):
        self.model.fit(dataset)
        if for_train:
            self.is_fitted_for_train = True  # TODO: keep multiple fitted instances?
            self.is_fitted_for_recommend = False
        else:
            self.is_fitted_for_train = False
            self.is_fitted_for_recommend = True

    def generate_candidates(
        self,
        users: tp.List[int],
        dataset: Dataset,
        filter_viewed: bool,
        for_train: bool,
        items_to_recommend: tp.Optional[tp.List[int]] = None,
    ) -> pd.DataFrame:
        
        if for_train and not self.is_fitted_for_train:
            raise NotFittedError(self.__class__.__name__)
        if not for_train and not self.is_fitted_for_recommend:
            raise NotFittedError(self.__class__.__name__)
        
        candidates = self.model.recommend(
            users=users,
            dataset=dataset,
            k=self.num_candidates,
            filter_viewed=filter_viewed,
            items_to_recommend=items_to_recommend,
            add_rank_col=self.keep_ranks,
        )
        return candidates
    
    
class TwoStageModel(ModelBase):
    """
    Two Stage Model for recommendation systems.
    """

    def __init__(
        self,
        candidate_generators: tp.List[CandidateGenerator],
        splitter: Splitter,
        reranker: RerankerBase,
        sampler: NegativeSamplerBase = PerUserNegativeSampler(),
        feature_collector: CandidatesFeatureCollector = CandidatesFeatureCollector(),
        verbose: int = 0,
    ) -> None:
        """
        Initialize the TwoStageModel with candidate generators, splitter, reranker, sampler, and feature collector.

        Parameters
        ----------
        candidate_generators : tp.List[CandidateGenerator]
            List of candidate generators.
        splitter : Splitter
            Splitter for dataset splitting.
        reranker : Reranker
            Reranker for reranking candidates.
        sampler : NegativeSamplerBase, optional
            Sampler for negative sampling. Default is PerUserNegativeSampler().
        feature_collector : CandidatesFeatureCollector, optional
            Collector for user-item features. Default is CandidatesFeatureCollector().
        verbose : int, optional
            Verbosity level. Default is 0.
        """

        super().__init__(verbose=verbose)
        
        if hasattr(splitter, "n_splits"):
            assert splitter.n_splits == 1  # TODO: handle softly
        self.splitter = splitter
        self.sampler = sampler
        self.reranker = reranker
        self.cand_gen_dict = self._create_cand_gen_dict(candidate_generators)
        self.feature_collector = feature_collector
        
    def _create_cand_gen_dict(self, candidate_generators: tp.List[CandidateGenerator]) -> tp.Dict[str, CandidateGenerator]:
        """
        Create a dictionary of candidate generators with unique identifiers.

        Parameters
        ----------
        candidate_generators : tp.List[CandidateGenerator]
            List of candidate generators.

        Returns
        -------
        tp.Dict[str, CandidateGenerator]
            Dictionary with candidate generator identifiers as keys and candidate generators as values.
        """
        model_count = {}
        cand_gen_dict = {}
        for candgen in candidate_generators:
            model_name = candgen.model.__class__.__name__
            if model_name not in model_count:
                model_count[model_name] = 0
            model_count[model_name] += 1
            identifier = f"{model_name}_{model_count[model_name]}"
            cand_gen_dict[identifier] = candgen
        return cand_gen_dict

    def _split_to_history_dataset_and_train_targets(
            self, dataset: Dataset, splitter: Splitter
            ) -> tp.Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Split interactions into history and train sets for first-stage and second-stage model training.

        Parameters
        ----------
        dataset : Dataset
            The dataset to split.
        splitter : Splitter
            The splitter to use for splitting the dataset.

        Returns
        -------
        tp.Tuple[pd.DataFrame, pd.DataFrame]
            Tuple containing the history dataset, train targets, and fold information.
        """
        split_iterator = splitter.split(dataset.interactions, collect_fold_stats=True)

        train_ids, test_ids, fold_info = next(iter(split_iterator))  # splitter has only one fold

        # We prepare dataset and train targets with external ids
        # This wat user can easily join features for candidates
        history_dataset = splitter.get_train_dataset(dataset, train_ids, keep_external_ids=True)  # external
        train_targets = dataset.get_raw_interactions().iloc[test_ids]  # external

        return history_dataset, train_targets, fold_info

    def _fit(self, dataset: Dataset, *args: tp.Any, **kwargs: tp.Any) -> None:
        """
        Fits all first-stage models on history dataset
        Generates candidates
        Sets targets
        Samples negatives
        Collects features for candidates
        Trains reranker on prepared train
        Fits all first-stage models on full dataset
        """
        train_with_target = self.get_train_with_targets_for_reranker(dataset)  # external ids
        self.reranker.fit(train_with_target)  # external ids
        self._fit_first_cadidate_generators(dataset, for_train=False)  # external ids
        
    def get_train_with_targets_for_reranker(self, dataset: Dataset) -> None:
        """
        Prepare training data for the reranker.

        Parameters
        ----------
        dataset : Dataset
            The dataset to prepare training data from.

        Returns
        -------
        pd.DataFrame
            DataFrame containing training data with targets and 2 extra columns: `Columns.User`, `Columns.Item`.
        """
        history_dataset, train_targets, fold_info = self._split_to_history_dataset_and_train_targets(dataset, self.splitter)

        self._fit_first_cadidate_generators(history_dataset, for_train=True)
        
        candidates = self._get_candidates_from_first_stage(
            users=train_targets[Columns.User].unique(),  # external
            dataset=history_dataset,  # external
            filter_viewed=self.splitter.filter_already_seen,  # TODO: think about it
            for_train=True,
        )
        candidates = self._set_targets_to_candidates(candidates, train_targets)
        candidates = self.sampler.sample_negatives(candidates)
        
        train_with_target = self.feature_collector.collect_features(candidates, history_dataset, fold_info)
        
        return train_with_target
        
    def _set_targets_to_candidates(self, candidates: pd.DataFrame, train_targets: pd.DataFrame) -> pd.DataFrame:
        """
        Set target values to the candidate items.

        Parameters
        ----------
        candidates : pd.DataFrame
            DataFrame containing candidate items.
        train_targets : pd.DataFrame
            DataFrame containing training targets.

        Returns
        -------
        pd.DataFrame
            DataFrame with target values set.
        """
        train_targets["target"] = 1
        
        # Remember that this way we exclude positives that weren't present in candidates
        train = pd.merge(
            candidates,
            train_targets[[Columns.User, Columns.Item, "target"]],
            how="left",
            on=Columns.UserItem,
        )
        
        train["target"] = train["target"].fillna(0).astype("int32")
        return train

        
    def _fit_first_cadidate_generators(self, dataset: Dataset, for_train: bool) -> None:
        """
        Fit the first-stage candidate generators on the dataset.

        Parameters
        ----------
        dataset : Dataset
            The dataset to fit the candidate generators on.
        for_train : bool
            Whether the fitting is for training or not.
        """
        for candgen in self.cand_gen_dict.values():
            candgen.fit(dataset, for_train)

    def _get_candidates_from_first_stage(
        self,
        users: ExternalIds,
        dataset: Dataset,
        filter_viewed: bool,
        for_train: bool,
        items_to_recommend: tp.Optional[AnyIds] = None,
    ) -> pd.DataFrame:
        """
        Get candidates from the first-stage models.

        Parameters
        ----------
        users : ExternalIds
            List of user IDs to get candidates for.
        dataset : Dataset
            The dataset to get candidates from.
        filter_viewed : bool
            Whether to filter already viewed items.
        for_train : bool
            Whether the candidates are for training or not.
        items_to_recommend : tp.Optional[AnyIds], optional
            List of items to recommend. Default is None.

        Returns
        -------
        pd.DataFrame
            DataFrame containing the candidates.
        """
        candidates_dfs = []

        for identifier, candgen in self.cand_gen_dict.items():
            candidates = candgen.generate_candidates(
                users=users,
                dataset=dataset,
                filter_viewed=filter_viewed,
                for_train=for_train,
                items_to_recommend=items_to_recommend
            )

            # Process ranks and scores as features
            rank_col_name, score_col_name = f"{identifier}_rank", f"{identifier}_score"
            if not candgen.keep_scores:
                candidates.drop(columns=Columns.Score, inplace=True)
            candidates.rename(
                columns={Columns.Rank: rank_col_name, Columns.Score: score_col_name},
                inplace=True,
                errors="ignore",
            )
            candidates_dfs.append(candidates)

        # Merge all candidates together and process missing ranks and scores
        all_candidates = reduce(
            lambda a, b: a.merge(b, how="outer", on=Columns.UserItem), candidates_dfs
        )
        first_stage_results = self._process_ranks_and_scores(all_candidates)

        return first_stage_results

    def _process_ranks_and_scores(
        self,
        all_candidates: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Process ranks and scores of the candidates.

        Parameters
        ----------
        all_candidates : pd.DataFrame
            DataFrame containing all candidates.

        Returns
        -------
        pd.DataFrame
            DataFrame with processed ranks and scores.
        """

        for identifier, candgen in self.cand_gen_dict.items():
            rank_col_name, score_col_name = f"{identifier}_rank", f"{identifier}_score"
            if candgen.keep_ranks:
                all_candidates[rank_col_name] = all_candidates[rank_col_name].fillna(
                    candgen.ranks_fillna_value
                )
            if candgen.keep_scores:
                all_candidates[score_col_name] = all_candidates[score_col_name].fillna(
                    candgen.scores_fillna_value
                )

        return all_candidates
    
    def recommend(
        self,
        users: AnyIds,
        dataset: Dataset,
        k: int,
        filter_viewed: bool,
        items_to_recommend: tp.Optional[AnyIds] = None,
        add_rank_col: bool = True,
        assume_external_ids: bool = True,
    ) -> pd.DataFrame:
        self._check_is_fitted()
        self._check_k(k)
        
        if not assume_external_ids:  # TODO: THINK ABOUT IT
            raise ValueError("TwoStageModel cannot recommend in internal ids because it relies on feature collection in External Ids only")
        
        try:
            candidates = self._get_candidates_from_first_stage(
                users=users,  # external
                dataset=dataset,  # external
                filter_viewed=filter_viewed,  # TODO: think about it
                items_to_recommend=items_to_recommend,
                for_train=False,
            )
        except NotFittedError:
            self._fit_first_cadidate_generators(dataset, for_train=False)
            candidates = self._get_candidates_from_first_stage(
                users=users,
                dataset=dataset,
                filter_viewed=filter_viewed, 
                items_to_recommend=items_to_recommend,
                for_train=False,
            )
        
        train = self.feature_collector.collect_features(candidates, dataset, fold_info=None)
        
        reco = self.reranker.rerank(train)
        
        if add_rank_col:
            reco[Columns.Rank] = reco.groupby(Columns.User, sort=False).cumcount() + 1
            
        return reco