from __future__ import unicode_literals
from future.builtins import *
import six
from django.utils.encoding import smart_text


from myrg_core.classes import RobogalsAPIView
from rest_framework.parsers import FileUploadParser
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from django.db.models.fields import FieldDoesNotExist
from django.db.models import Q
from django.db import transaction
from django.utils import timezone

from .models import RepoContainer, RepoFile
from .serializers import RepoContainerSerializer, RepoFileSerializer


PAGINATION_MAX_LENGTH = 1000

MAX_REPOS = 1
        
# Repo Container
################################################################################
class ListRepoContainers(RobogalsAPIView):
    def post(self, request, format=None):
        from myrg_users.serializers import RobogalsUserSerializer
        from myrg_users.models import RobogalsUser

        # request.DATA
        try:
            requested_fields = list(request.DATA.get("query"))
            requested_pagination = dict(request.DATA.get("pagination"))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
            
        if (not requested_fields) or (not requested_pagination):
            return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
        
        
        # Pagination
        pagination_page_index = requested_pagination.get("page")
        pagination_page_length = requested_pagination.get("length")
        
        if (pagination_page_index is None) or (pagination_page_length is None):
            return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
        
        pagination_page_index = int(pagination_page_index)
        pagination_page_length = int(pagination_page_length)
        
        pagination_start_index = pagination_page_index * pagination_page_length
        pagination_end_index = pagination_start_index + (pagination_page_length if pagination_page_length < PAGINATION_MAX_LENGTH else PAGINATION_MAX_LENGTH)
            
        if pagination_start_index < 0 or pagination_end_index < 0:
            return Response({"detail":"PAGINATION_NEGATIVE_INDEX_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)
        
        
        # Filter
        filter_dict = {} 
        sort_fields = []
        fields = ["id", "user", "role"] 
        
        for field_object in requested_fields:
            field_name = field_object.get("field")
            field_query = field_object.get("search")
            field_order = field_object.get("order") 
            field_visibility = field_object.get("visibility")  
            
            if (field_name is None):
                return Response({"detail":"FIELD_IDENTIFIER_MISSING"}, status=status.HTTP_400_BAD_REQUEST)
            
            field_name = str(field_name)
            
            # Block protected fields 
            if field_name in RepoContainer.PROTECTED_FIELDS:
                return Response({"detail":"`{}` is a protected field.".format(field_name)}, status=status.HTTP_400_BAD_REQUEST)
            
            # Non-valid field names
            # ! Uses _meta non-documented API
            try:
                RepoContainer._meta.get_field_by_name(field_name)
            except FieldDoesNotExist:
                return Response({"detail":"`{}` is not a valid field name.".format(field_name)}, status=status.HTTP_400_BAD_REQUEST)
                
            if (field_query is not None):
                filter_dict.update({field_name+"__icontains": str(field_query)})
            
            if (field_order is not None):
                field_order = str(field_order)
                
                if field_order == "a":
                    sort_fields.append(field_name)
                if field_order == "d":
                    sort_fields.append("-"+field_name)
            
            if not (field_visibility == False):
                fields.append(field_name)
        
        
        # Build query
        query = RepoContainer.objects.filter(service__gt=0)
        query = query.filter(**filter_dict)
        query = query.order_by(*sort_fields)
        
        query_size = query.count()
        
        query = query[pagination_start_index:pagination_end_index]
        
        
        # Serialize
        serializer = RepoContainerSerializer
        serializer.Meta.fields = fields
        
        serialized_query = serializer(query, many=True)
        
        # Output
        output_list = [] 
        
        for repocontainer_object in serialized_query.data:
            new_dict = {}
            new_dict.update({"id": repocontainer_object.pop("id")})
            new_dict.update({"data": repocontainer_object})
            # checked user property and retrieve information for user(from user model) 
            # http://stackoverflow.com/questions/11748234/
            if repocontainer_object.get('user'):
                user_id = repocontainer_object.pop("user")
                user = RobogalsUser.objects.filter(id = user_id)
                user_serializer = RobogalsUserSerializer
                user_serializer.Meta.fields = ("username",)
                user_serializer_query = user_serializer(user, many=True)
                user_data = user_serializer_query.data
                new_dict.update({"user": user_data})
        
            output_list.append(new_dict)   
        
        
        return Response({ 
                            "meta": {
                                "size": query_size
                            }, 
                            "rcl": output_list
                        })

class DeleteRepoContainers(RobogalsAPIView):
    def post(self, request, format=None):
        # request.DATA
        try:
            requested_ids = list(set(request.DATA.get("id")))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
        
        if (not requested_ids):
            return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
        
        
        # Filter out bad IDs 
        ids_to_remove = []
        failed_ids = {}
        affected_ids = []
        
        for idx,pk in enumerate(requested_ids):
            if not isinstance(pk, int):
                ids_to_remove.append(idx)
                failed_ids.update({pk: "DATA_FORMAT_INVALID"})
                continue
                    
            ####################################################################
            # Permission restricted deletion to be implemented here
            #
            # if not permission_allows_deletion_of_this_id:
            #   ids_to_remove.append(idx)
            #   failed_ids.update({pk: "PERMISSION_DENIED"})
            ####################################################################
        
        # Remove bad IDs
        requested_ids = [pk for idx,pk in enumerate(requested_ids) if idx not in ids_to_remove]
        
        # Run query
        try:
            with transaction.atomic():
                query = RepoContainer.objects.filter(service__gt=0, id__in=requested_ids)
                affected_ids = [obj.get("id") for obj in query.values("id")]
                affected_num_rows = query.update(service=0)
        except:
            for pk in requested_ids:
                failed_ids.update({pk: "OBJECT_NOT_MODIFIED"})

        # Gather up non-deleted IDs
        non_deleted_ids = list(set(requested_ids)-set(affected_ids))
        
        for pk in non_deleted_ids:
            failed_ids.update({pk: "OBJECT_NOT_MODIFIED"})
        
        
        
        return Response({
            "fail": {
                "id": failed_ids,
            },
            "success": {
                "id": affected_ids
            }
        })
        
class EditRepoContainers(RobogalsAPIView):
    def post(self, request, format=None):
        # request.DATA
        try:
            supplied_repocontaineres = list(request.DATA.get("repo_container"))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
                
        failed_repocontainer_updates = {}
        completed_repocontainer_updates = []
        
        # Filter out bad data
        for repocontainer_object in supplied_repocontaineres:
            skip_repocontainer = False
            repocontainer_update_dict = {}
            
            
            try:
                repocontainer_id = int(repocontainer_object.get("id"))
                repocontainer_data = dict(repocontainer_object.get("data"))
            except:
                return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
            
            if (roleclass_id is None):
                return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
            
            for field,value in six.iteritems(roleclass_data):
                field = str(field)
                
                # Read only fields
                if field in RepoContainer.READONLY_FIELDS:
                    failed_repocontainer_updates.update({roleclass_id: "FIELD_READ_ONLY"})
                    skip_repocontainer = True
                    break
                
                # Non-valid field names
                # ! Uses _meta non-documented API
                try:
                    RepoContainer._meta.get_field_by_name(field)
                except FieldDoesNotExist:
                    failed_repocontainer_updates.update({roleclass_id: "FIELD_IDENTIFIER_INVALID"})
                    skip_repocontainer = True
                    break
                    
                ################################################################
                # Permission restricted editing to be implemented here
                #
                # if not permission_allows_editing_of_this_id:
                #   failed_roleclass_updates.update({pk: "PERMISSION_DENIED"})
                #   skip_roleclass = True
                #   break
                ################################################################
            
                # Add to update data dict
                roleclass_update_dict.update({field: value})
            
            if skip_repocontainer:
                continue
            
            
            # Fetch, serialise and save
            try:
                repocontainer_query = RepoContainer.objects.get(pk=roleclass_id)
            except:
                failed_repocontainer_updates.update({repocontainer_id: "OBJECT_NOT_FOUND"})
                continue
                
            serializer = RepoContainerSerializer
            serialized_group = serializer(repocontainer_query, data=repocontainer_update_dict, partial=True)
        
            if serialized_repocontainer.is_valid():
                try:
                    with transaction.atomic():
                        serialized_repocontainer.save()
                        completed_repocontainer_updates.append(roleclass_id)
                except:
                    failed_repocontainer_updates.update({repocontainer_id: "OBJECT_NOT_MODIFIED"})
            else:
                failed_repocontainer_updates.update({repocontainer_id: "DATA_VALIDATION_FAILED"})
                
        return Response({
            "fail": {
                "id": failed_repocontainer_updates
            },
            "success": {
                "id": completed_repocontainer_updates
            }
        })

class CreateRepoContainers(RobogalsAPIView):
    def post(self, request, format=None):
        # request.DATA
        try:
            supplied_repocontainers = list(request.DATA.get("rc"))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
                
        if len(supplied_repocontainers) > MAX_REPOS:
            return Response({"detail":"REQUEST_OVER_OBJECT_LIMIT"}, status=status.HTTP_400_BAD_REQUEST)
        
        failed_repocontainer_creations = {}
        completed_repocontainer_creations = {}
        
        # Filter out bad data
        for repocontainer_object in supplied_repocontainers:
            skip_repocontainer = False
            repocontainer_create_dict = {}
            
            try:  
                repocontainer_nonce = repocontainer_object.get("nonce")
                repocontainer_data = dict(repocontainer_object.get("data"))
            except:
                return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
            
            if (repocontainer_nonce is None):
                return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
            
            for field,value in six.iteritems(repocontainer_data):
                field = str(field)
                
                # Read only fields
                if field in RepoContainer.READONLY_FIELDS:
                    failed_repocontainer_creations.update({repocontainer_nonce: "FIELD_READ_ONLY"})
                    skip_repocontainer = True
                    break
                
                # Non-valid field names
                # ! Uses _meta non-documented API
                try:
                    RepoContainer._meta.get_field_by_name(field)
                except FieldDoesNotExist:
                    failed_repocontainer_creations.update({repocontainer_nonce: "FIELD_IDENTIFIER_INVALID"})
                    skip_repocontainer = True
                    break
            
            
                # Add to update data dict
                repocontainer_create_dict.update({field: value})
            
            if skip_repocontainer: 
                continue  
            
            # Serialise and save
            serializer = RepoContainerSerializer
            serialized_repocontainer = serializer(data=repocontainer_create_dict)
            
            if serialized_repocontainer.is_valid():
                try:
                    with transaction.atomic():
                         repocontainer = serialized_repocontainer.save()
                         completed_repocontainer_creations.update({repocontainer_nonce: repocontainer.id})
                except:
                    failed_repocontainer_creations.update({repocontainer_nonce: "OBJECT_NOT_MODIFIED"})
            else:
                failed_repocontainer_creations.update({repocontainer_nonce: "DATA_VALIDATION_FAILED"})
                
        return Response({
            "fail": {
                "nonce": serialized_repocontainer.errors #repocontainer_create_dict#failed_repocontainer_creations
            },
            "success": {
                "nonce_id": completed_repocontainer_creations
            },
            "msg": serialized_repocontainer  
        })
        
        
# RepoFile
################################################################################
class ListRepoFiles(RobogalsAPIView):
    def post(self, request, format=None):
        # request.DATA
        try:
            requested_fields = list(request.DATA.get("query"))
            requested_pagination = dict(request.DATA.get("pagination"))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
            
        if (not requested_fields) or (not requested_pagination):
            return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
        
        
        # Pagination
        pagination_page_index = requested_pagination.get("page")
        pagination_page_length = requested_pagination.get("length")
        
        if (pagination_page_index is None) or (pagination_page_length is None):
            return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
         
        pagination_page_index = int(pagination_page_index)
        pagination_page_length = int(pagination_page_length)
        
        pagination_start_index = pagination_page_index * pagination_page_length
        pagination_end_index = pagination_start_index + (pagination_page_length if pagination_page_length < PAGINATION_MAX_LENGTH else PAGINATION_MAX_LENGTH)
            
        if pagination_start_index < 0 or pagination_end_index < 0:
            return Response({"detail":"PAGINATION_NEGATIVE_INDEX_UNSUPPORTED"}, status=status.HTTP_400_BAD_REQUEST)
        
         
        # Filter
        filter_dict = {}
        sort_fields = []
        fields = ["id"]  
        
        for field_object in requested_fields:
            field_name = field_object.get("field")
            field_query = field_object.get("search")
            field_order = field_object.get("order")
            field_visibility = field_object.get("visibility")
            
            if (field_name is None):
                return Response({"detail":"FIELD_IDENTIFIER_MISSING"}, status=status.HTTP_400_BAD_REQUEST)
            
            field_name = str(field_name)
             
            # Block protected fields like passwords
            if field_name in RepoFile.PROTECTED_FIELDS:
                return Response({"detail":"`{}` is a protected field.".format(field_name)}, status=status.HTTP_400_BAD_REQUEST)
            
            # Non-valid field names
            # ! Uses _meta non-documented API 
            try:
                RepoFile._meta.get_field_by_name(field_name)
            except FieldDoesNotExist:
                return Response({"detail":"`{}` is not a valid field name.".format(field_name)}, status=status.HTTP_400_BAD_REQUEST)
                
            if (field_query is not None and field_name == "container"):
                filter_dict.update({field_name+"__id__icontains": str(field_query)})
            elif (field_query is not None):
                filter_dict.update({field_name+"__icontains": str(field_query)})
            
            if (field_order is not None):
                field_order = str(field_order) 
                
                if field_order == "a":
                    sort_fields.append(field_name)
                if field_order == "d":
                    sort_fields.append("-"+field_name)
            
            if not (field_visibility == False):
                fields.append(field_name)
        
        
        # Build query
        query = RepoFile.objects.all()
        query = query.filter(**filter_dict)
        query = query.order_by(*sort_fields)
        
        query_size = query.count()
        
        query = query[pagination_start_index:pagination_end_index]
        
        
        # Serialize
        serializer = RepoFileSerializer
        serializer.Meta.fields = fields
        
        serialized_query = serializer(query, many=True)
        
          
        # Output
        output_list = []
        
        for repofile_object in serialized_query.data:
            new_dict = {}
            new_dict.update({"id": repofile_object.pop("id")})
            new_dict.update({"data": repofile_object})
        
            output_list.append(new_dict)
        
        
        return Response({
                            "meta": {
                                "size": query_size
                            },
                            "rfl": output_list
                        })

class EditRepoFiles(RobogalsAPIView):
    def post(self, request, format=None):
        # request.DATA
        try:
            supplied_repofiles = list(request.DATA.get("rf"))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
                
        failed_repofile_updates = {}
        completed_repofile_updates = []
        
        # Filter out bad data
        for repofile_object in supplied_repofiles:
            skip_repofile = False
            repofile_update_dict = {}
            
            
            try:
                repofile_id = int(repofile_object.get("id"))
                repofile_data = dict(repofile_object.get("data"))
            except:
                return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
            
            if (role_id is None):
                return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
            
            for field,value in six.iteritems(repofile_data):
                field = str(field)
                
                # Read only fields
                if field in RepoFile.READONLY_FIELDS:
                    failed_repofile_updates.update({repofile_id: "FIELD_READ_ONLY"})
                    skip_repofile = True
                    break
                
                # Non-valid field names
                # ! Uses _meta non-documented API
                try:
                    RepoFile._meta.get_field_by_name(field)
                except FieldDoesNotExist:
                    failed_repofile_updates.update({repofile_id: "FIELD_IDENTIFIER_INVALID"})
                    skip_repofile = True
                    break
                     
                ################################################################
                # Permission restricted editing to be implemented here
                #
                # if not permission_allows_editing_of_this_id:
                #   failed_role_updates.update({pk: "PERMISSION_DENIED"})
                #   skip_role = True
                #   break
                ################################################################
            
                # Add to update data dict
                repofile_update_dict.update({field: value})
            
            if skip_repofile:
                continue
            
            
            # Fetch, serialise and save
            try:
                repofile_query = RepoFile.objects.get(pk=role_id)
            except:
                failed_repofile_updates.update({repofile_id: "OBJECT_NOT_FOUND"})
                continue
                
            serializer = RepoFileSerializer
            serialized_repofile = serializer(repofile_query, data=repofile_update_dict, partial=True)
        
            if serialized_repofile.is_valid():
                try: 
                    with transaction.atomic():
                        serialized_repofile.save()
                        completed_repofile_updates.append(repofile_id)
                except:
                    failed_repofile_updates.update({repofile_id: "OBJECT_NOT_MODIFIED"})
            else:
                failed_repofile_updates.update({repofile_id: "DATA_VALIDATION_FAILED"})
                
        return Response({
            "fail": {
                "id": failed_repofile_updates
            },
            "success": {
                "id": completed_repofile_updates
            }
        })

class CreateRepoFiles(RobogalsAPIView):
    #parser_classes = (FileUploadParser,)
    def post(self, request, format=None):
        # request.DATA
        try:
            supplied_repofiles = list(request.DATA.get("rf"))
        except:
            return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
                
        failed_repofile_creations = {}
        completed_repofile_creations = {}
        
        # Filter out bad data
        for repofile_object in supplied_repofiles:
            skip_repofile = False
            repofile_create_dict = {}
            
            try:
                repofile_nonce = repofile_object.get("nonce")
                repofile_data = dict(repofile_object.get("data"))
            except:
                return Response({"detail":"DATA_FORMAT_INVALID"}, status=status.HTTP_400_BAD_REQUEST)
            
            if (repofile_nonce is None):
                return Response({"detail":"DATA_INSUFFICIENT"}, status=status.HTTP_400_BAD_REQUEST)
            
            for field,value in six.iteritems(repofile_data):
                field = str(field)
                
                # Read only fields
                if field in RepoFile.READONLY_FIELDS:
                    failed_repofile_creations.update({repofile_nonce: "FIELD_READ_ONLY"})
                    skip_repofile = True
                    break
                
                # Non-valid field names
                # ! Uses _meta non-documented API
                try:
                    RepoFile._meta.get_field_by_name(field)
                except FieldDoesNotExist:
                    failed_repofile_creations.update({repofile_nonce: "FIELD_IDENTIFIER_INVALID"})
                    skip_repofile = True
                    break
              
            
                # Add to update data dict
                repofile_create_dict.update({field: value})
            
            if skip_repofile:
                continue 
               
            
            # Serialise and save
            serializer = RepoFileSerializer
            serialized_repofile = serializer(data=repofile_create_dict, files=request.FILES)
            
            if serialized_repofile.is_valid():
                try:
                    with transaction.atomic():
                        repofile = serialized_repofile.save()
                        completed_repofile_creations.update({repofile_nonce: role.id})
                except:
                    failed_repofile_creations.update({repofile_nonce: "OBJECT_NOT_MODIFIED"})
            else:
                failed_repofile_creations.update({repofile_nonce: "DATA_VALIDATION_FAILED"})
                
        return Response({
            "fail": {
                "nonce": failed_repofile_creations
            },
            "success": {
                "nonce_id": completed_repofile_creations
            },
            "error": {
                "message": serialized_repofile.errors
            },
        })

        
        
        
        